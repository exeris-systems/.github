"""remove_signing_key: the private key is gone and the post-condition is checked, not assumed."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

import caps_release_helpers as h

S = "remove_signing_key"

DOUBLE = """#!/bin/sh
tool="$(basename "$0")"
if [ -d "${GNUPGHOME:-/nonexistent}" ]; then exists=yes; else exists=no; fi
printf '%s\\t%s\\t%s\\t%s\\n' "$tool" "$*" "$GNUPGHOME" "$exists" >> "$FAKE_LOG"
case " $* " in
  *" --import "*) printf '%s' "$FAKE_IMPORT_ERR" >&2; exit "${FAKE_IMPORT_RC:-0}" ;;
  *" --list-secret-keys "*) printf '%s' "$FAKE_LIST_OUT"; exit "${FAKE_LIST_RC:-0}" ;;
esac
exit 0
"""


class Doubles(h.Case):
    def setUp(self):
        super().setUp()
        self.fake = self.write("bin/fake", DOUBLE)
        os.chmod(self.fake, 0o755)
        self.gpg = self.path("bin", "gpg")
        self.gpgconf = self.path("bin", "gpgconf")
        os.symlink(self.fake, self.gpg)
        os.symlink(self.fake, self.gpgconf)
        self.log = self.path("calls.log")
        self.secret = self.path("secret")
        self.verify = self.path("verify")
        self.key = self.path("pub.asc")
        self.envfile = self.path("env")

    def prepare(self, secret=True, key="PUBLIC KEY\n", env_content=""):
        if secret:
            os.makedirs(self.secret, exist_ok=True)
            with open(os.path.join(self.secret, "private-keys-v1.d"), "w") as fh:
                fh.write("PRIVATE")
        if key is not None:
            with open(self.key, "w") as fh:
                fh.write(key)
        with open(self.envfile, "w") as fh:
            fh.write(env_content)

    def argv(self, **over):
        values = dict(secret_home=self.secret, verify_home=self.verify, public_key=self.key, env_file=self.envfile,
                      gpg=self.gpg, gpgconf=self.gpgconf)
        values.update(over)
        return [x for k, v in values.items() if v is not None for x in ("--" + k.replace("_", "-"), v)]

    def invoke(self, argv=None, **env):
        full = h.clean_env(FAKE_LOG=self.log, **env)
        return h.run_main(S, argv or self.argv(), env=full)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        out = []
        with open(self.log) as fh:
            for ln in fh:
                tool, args, home, exists = ln.rstrip("\n").split("\t")
                out.append({"tool": tool, "args": args.split(), "home": home, "home_exists": exists == "yes"})
        return out

    def env_lines(self):
        with open(self.envfile) as fh:
            text = fh.read()
        self.assertTrue(text == "" or text.endswith("\n"), "every env line ends with a newline")
        return text.splitlines()


class Removal(Doubles):
    def test_the_whole_removal(self):
        self.prepare(env_content="KEEP=1\n")
        res = self.invoke()
        self.accepted(res)
        self.assertIn("ok - the private key is gone", res.out)
        self.assertFalse(os.path.exists(self.secret))
        self.assertFalse(os.path.exists(self.key), "the exported public key file is deleted")
        self.assertEqual(stat.S_IMODE(os.stat(self.verify).st_mode), 0o700)
        self.assertEqual(self.env_lines(), ["KEEP=1", f"GNUPGHOME={self.verify}"])

    def test_the_agent_is_killed_in_the_secret_home_before_it_is_deleted(self):
        self.prepare()
        self.accepted(self.invoke())
        kill = [c for c in self.calls() if c["tool"] == "gpgconf"]
        self.assertEqual(len(kill), 1)
        self.assertEqual(kill[0]["args"], ["--kill", "gpg-agent"])
        self.assertEqual(kill[0]["home"], self.secret)
        self.assertTrue(kill[0]["home_exists"], "the agent is stopped while the home is still there")

    def test_the_public_key_is_imported_into_the_verify_home_only(self):
        self.prepare()
        self.accepted(self.invoke())
        gpg = [c for c in self.calls() if c["tool"] == "gpg"]
        imp = [c for c in gpg if "--import" in c["args"]]
        self.assertEqual(len(imp), 1)
        self.assertEqual(imp[0]["args"], ["--batch", "--import", self.key])
        self.assertEqual(imp[0]["home"], self.verify)
        listing = [c for c in gpg if "--list-secret-keys" in c["args"]]
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0]["home"], self.verify)
        self.assertEqual(self.calls().index(imp[0]) < self.calls().index(listing[0]), True)
        self.assertTrue(all(c["home"] != self.secret for c in gpg), "gpg never runs in the secret home")

    def test_an_existing_verify_home_is_tightened_to_700(self):
        self.prepare()
        os.makedirs(self.verify, mode=0o755)
        os.chmod(self.verify, 0o755)
        self.accepted(self.invoke())
        self.assertEqual(stat.S_IMODE(os.stat(self.verify).st_mode), 0o700)

    def test_an_absent_secret_home_is_fine(self):
        self.prepare(secret=False)
        self.accepted(self.invoke())
        self.assertEqual([c for c in self.calls() if c["tool"] == "gpgconf"], [])

    def test_a_missing_gpgconf_is_tolerated(self):
        self.prepare()
        self.accepted(self.invoke(self.argv(gpgconf=self.path("bin", "no-such"))))
        self.assertFalse(os.path.exists(self.secret))

    def test_the_env_file_is_appended_not_replaced_and_gets_one_line(self):
        self.prepare(env_content="A=1\nB=2\n")
        self.accepted(self.invoke())
        self.assertEqual(self.env_lines(), ["A=1", "B=2", f"GNUPGHOME={self.verify}"])

    def test_an_empty_or_missing_public_key_imports_nothing_and_is_still_deleted(self):
        for label, key in (("empty", ""), ("missing", None)):
            with self.subTest(label):
                shutil.rmtree(self.verify, ignore_errors=True)
                open(self.log, "w").close()
                self.prepare(key=key)
                if key is None and os.path.exists(self.key):
                    os.remove(self.key)
                self.accepted(self.invoke())
                self.assertEqual([c for c in self.calls() if "--import" in c["args"]], [])
                self.assertFalse(os.path.exists(self.key))

    def test_import_failure_is_a_refusal_but_the_key_is_still_removed(self):
        self.prepare()
        res = self.invoke(FAKE_IMPORT_RC="2", FAKE_IMPORT_ERR="gpg: no valid OpenPGP data found")
        self.refused(res, "could not be imported")
        self.assertIn("no valid OpenPGP data", res.errors()[0])
        self.assertFalse(os.path.exists(self.secret))
        self.assertFalse(os.path.exists(self.key))

    def test_a_secret_key_listed_after_removal_is_a_refusal(self):
        self.prepare()
        self.refused(self.invoke(FAKE_LIST_OUT="sec:u:255:22:ABCDEF:1:::::\nfpr:::\n"), "secret key is still")

    def test_secret_lines_other_than_sec_are_not_a_listing_of_secret_keys(self):
        self.prepare()
        self.accepted(self.invoke(FAKE_LIST_OUT="pub:u:255:22:ABCDEF\nuid:u::::\n"))

    def test_the_listing_exit_status_is_judged(self):
        for rc, ok in ((0, True), (2, True), (1, False), (3, False), (127, False)):
            with self.subTest(rc):
                shutil.rmtree(self.verify, ignore_errors=True)
                self.prepare()
                res = self.invoke(FAKE_LIST_RC=str(rc))
                (self.accepted if ok else self.refused)(res)

    def test_a_private_keyring_that_cannot_be_deleted_is_a_refusal(self):
        self.prepare()
        locked = os.path.join(self.secret, "locked")
        os.makedirs(locked)
        with open(os.path.join(locked, "key"), "w") as fh:
            fh.write("PRIVATE")
        os.chmod(locked, 0o500)
        self.refused(self.invoke(), "private keyring still exists")
        os.chmod(locked, 0o700)

    def test_a_verify_home_equal_to_or_inside_the_secret_home_is_a_refusal(self):
        for label, verify in (("equal", self.secret), ("inside", os.path.join(self.secret, "v"))):
            with self.subTest(label):
                shutil.rmtree(self.secret, ignore_errors=True)
                open(self.envfile, "w").close()
                self.prepare()
                self.refused(self.invoke(self.argv(verify_home=verify)), "private keyring still exists")

    def test_a_secret_home_that_is_a_symlink_is_a_refusal_and_the_link_is_not_followed_for_deletion(self):
        real = self.path("real-secret")
        os.makedirs(real)
        with open(os.path.join(real, "private"), "w") as fh:
            fh.write("PRIVATE")
        os.symlink(real, self.secret)
        self.prepare(secret=False)
        self.refused(self.invoke(), "private keyring still exists")
        self.assertTrue(os.path.islink(self.secret))
        self.assertTrue(os.path.isdir(real), "nothing was deleted through the link")

    def test_both_the_refusal_and_the_success_use_the_same_exit_codes_as_a_subprocess(self):
        for rc_env, want in (({}, 0), ({"FAKE_LIST_OUT": "sec:u\n"}, 1), ({"FAKE_IMPORT_RC": "2"}, 1)):
            with self.subTest(rc_env):
                shutil.rmtree(self.verify, ignore_errors=True)
                self.prepare()
                env = h.clean_env(FAKE_LOG=self.log, **rc_env)
                proc = subprocess.run([sys.executable, "-I", "-B", h.script_path(S), *self.argv()], env=env,
                                      capture_output=True, text=True)
                self.assertEqual(proc.returncode, want, proc)
                self.assertEqual(proc.stderr.count("::error::") > 0, want == 1)

    def test_usage(self):
        self.assertEqual(h.run_proc(S, ["--secret-home", "x"]).rc, 2)
        self.assertEqual(h.run_main(S, []).rc, 2)

    def test_a_gpg_that_cannot_run_does_not_pass_silently(self):
        self.prepare()
        res = h.run_proc(S, self.argv(gpg=self.path("bin", "no-such")), env=h.clean_env(FAKE_LOG=self.log))
        self.assertNotEqual(res.rc, 0)
        self.assertFalse(os.path.exists(self.secret))

    def test_a_verify_home_holding_a_control_character_is_refused(self):
        self.prepare()
        evil = self.verify + "\nEVIL=1"
        res = self.invoke(self.argv(verify_home=evil))
        self.refused(res)
        self.assertNotIn("EVIL=1", self.env_lines())


@unittest.skipUnless(h.have_gpg(), "gpg is not installed")
class RealBase(h.Case):
    """Real gpg: a throwaway key in a temporary keyring, removed by the script. Holds no test of its own."""

    def setUp(self):
        super().setUp()
        self.base = tempfile.mkdtemp(prefix="rsk-")
        self.addCleanup(self.cleanup_base)
        self.secret = os.path.join(self.base, "s")
        self.verify = os.path.join(self.base, "v")
        self.key = os.path.join(self.base, "pub.asc")
        self.envfile = os.path.join(self.base, "env")
        os.mkdir(self.secret, 0o700)
        self.env = h.clean_env(GNUPGHOME=self.secret)
        done = self.gpg("--pinentry-mode", "loopback", "--passphrase", "", "--quick-generate-key",
                        "Throwaway <t@invalid>", "ed25519", "sign", "1d", check=False)
        if done.returncode != 0:
            raise unittest.SkipTest("gpg cannot generate a key here: " + done.stderr)
        self.fpr = [ln for ln in self.gpg("--with-colons", "--list-keys").stdout.splitlines()
                    if ln.startswith("fpr:")][0].split(":")[9]
        self.assertEqual(len(self.secret_keys(self.secret)), 1)

    def cleanup_base(self):
        for d in (self.secret, self.verify):
            subprocess.run(["gpgconf", "--homedir", d, "--kill", "gpg-agent"], capture_output=True,
                           stdin=subprocess.DEVNULL)
        shutil.rmtree(self.base, ignore_errors=True)

    def gpg(self, *args, home=None, check=True):
        env = h.clean_env(GNUPGHOME=home or self.secret)
        return subprocess.run(["gpg", "--batch", *args], env=env, capture_output=True, text=True, check=check,
                              stdin=subprocess.DEVNULL, timeout=60)

    def export(self, secret=False):
        out = self.gpg("--armor", "--pinentry-mode", "loopback", "--passphrase", "",
                       "--export-secret-keys" if secret else "--export").stdout
        with open(self.key, "w") as fh:
            fh.write(out)

    def argv(self):
        return ["--secret-home", self.secret, "--verify-home", self.verify, "--public-key", self.key,
                "--env-file", self.envfile]

    def secret_keys(self, home):
        out = self.gpg("--with-colons", "--list-secret-keys", home=home, check=False).stdout
        return [ln for ln in out.splitlines() if ln.startswith("sec")]

    def removal(self, runner):
        victim = self.path("data")
        with open(victim, "w") as fh:
            fh.write("payload")
        self.gpg("--armor", "--pinentry-mode", "loopback", "--passphrase", "", "--detach-sign", "-o", victim + ".asc", victim)
        self.export()
        sock = subprocess.run(["gpgconf", "--homedir", self.secret, "--list-dirs", "agent-socket"], capture_output=True,
                              text=True, stdin=subprocess.DEVNULL).stdout.strip()
        agent_was_running = os.path.exists(sock)
        res = runner(S, self.argv(), env=self.env)
        self.accepted(res)
        self.assertFalse(os.path.exists(self.secret))
        self.assertFalse(os.path.exists(self.key))
        self.assertEqual(self.secret_keys(self.verify), [])
        self.assertIn(self.fpr, self.gpg("--with-colons", "--list-keys", home=self.verify).stdout)
        self.assertEqual(stat.S_IMODE(os.stat(self.verify).st_mode), 0o700)
        with open(self.envfile) as fh:
            self.assertEqual(fh.read(), f"GNUPGHOME={self.verify}\n")
        good = self.gpg("--verify", victim + ".asc", victim, home=self.verify, check=False)
        self.assertEqual(good.returncode, 0, good.stderr)
        if agent_was_running:
            self.assertFalse(os.path.exists(sock), "the gpg-agent of the secret home was killed")

@unittest.skipUnless(h.have_gpg(), "gpg is not installed")
class RealGpg(RealBase):
    def test_the_secret_key_is_gone_and_the_public_key_verifies_in_process(self):
        self.removal(h.run_main)

    def test_the_secret_key_is_gone_and_the_public_key_verifies_as_a_subprocess(self):
        self.removal(h.run_proc)

    def test_a_public_file_that_actually_holds_the_secret_key_is_a_refusal(self):
        self.export(secret=True)
        with open(self.key) as fh:
            self.assertIn("PRIVATE KEY", fh.read())
        res = h.run_main(S, self.argv(), env=self.env)
        self.refused(res, "secret key is still")
        self.assertFalse(os.path.exists(self.secret))
        self.assertFalse(os.path.exists(self.key))

    def test_after_a_refusal_no_secret_key_is_left_anywhere(self):
        self.export(secret=True)
        h.run_main(S, self.argv(), env=self.env)
        self.assertEqual(self.secret_keys(self.verify), [])

    def test_a_verify_home_that_already_holds_a_secret_key_is_a_refusal(self):
        os.mkdir(self.verify, 0o700)
        self.gpg("--pinentry-mode", "loopback", "--passphrase", "", "--quick-generate-key", "Stale <s@invalid>",
                 "ed25519", "sign", "1d", home=self.verify)
        self.export()
        self.refused(h.run_main(S, self.argv(), env=self.env), "secret key is still")

    def test_a_public_key_that_is_not_a_key_is_a_refusal(self):
        with open(self.key, "w") as fh:
            fh.write("not a key")
        self.refused(h.run_main(S, self.argv(), env=self.env), "could not be imported")
        self.assertFalse(os.path.exists(self.secret))


if __name__ == "__main__":
    unittest.main()
