# ⚡ Exeris Systems
**Building the World's First Hyper-Density PaaS & Cloud-Native Ecosystem**

[![Website](https://img.shields.io/badge/Website-exeris.eu-blue?style=flat-square)](https://exeris.eu)
[![Phase](https://img.shields.io/badge/Phase-Deep_R&D-orange?style=flat-square)](#)

## 👋 Hello There! Welcome to "The Wall"
We are **Exeris Systems**, an R&D initiative on a mission to end the era of **Cloud Waste** and **Vendor Lock-in**. We believe the current Enterprise software development model is fundamentally flawed—trapped between rigid, bloated Low-Code tools and the prohibitive costs of building from scratch. 

Instead of relying on the "Black Box" dogmas of legacy SaaS providers, we are designing a **"Transparent Glass Box"** architecture.

---

## 🏗️ What We Are Building
We are currently in the deep R&D phase, laying the groundwork for a comprehensive ecosystem. Our roadmap consists of three pillars:

### 1. ⚙️ Exeris Kernel (In Active Development)
This is the foundation we are building *right now*. It's a highly optimized, transactional I/O engine leveraging bleeding-edge JVM technologies—**Java 26 EA, Project Loom (Virtual Threads), and Valhalla (Value Objects)**—alongside native Linux capabilities (`io_uring`).
* **The Goal:** Achieve C/Rust-level determinism with Java productivity.
* **The Approach:** Enforcing an L0 architecture (Zero-GC, Zero-Copy on the hot-path) to drastically reduce memory footprint and latency.

### 2. 🎨 Exeris Studio & Universal SDK (Roadmap)
Once the Kernel is battle-tested, we will build the layers above it. We plan to bridge the gap between business analysts and software engineers with a visual environment that seamlessly syncs with raw, accessible code via an **"Instant Context Switch"** mechanism. 

### 3. 🛡️ The Ultimate Promise: Code Detachment
We refuse to build "golden cages". When an enterprise outgrows our future hosted platform, they will be able to license the underlying engine, detach their generated business logic, and host it on their own infrastructure. *We build systems that give you the keys to the exit.*

---

## 🍿 Fun Fact (What we eat for breakfast?)
We eat Java heap allocations for breakfast. 

But seriously, our favorite sight in the morning is a **flatline on a Java Flight Recorder (JFR) Garbage Collection graph**. While everyone else is busy tuning the Garbage Collector to handle millions of requests, we are simply making it redundant by relying on native memory slabs and flat value records.

## 🌈 Get Involved
While our core Enterprise Engine is currently in deep R&D, the **`exeris-kernel-spi`** (Service Provider Interfaces) and **Community Tier** components are being designed with openness in mind. We will be opening up repositories for architectural reviews and community contributions as soon as we stabilize our L0 contracts. Stay tuned!

## 👩‍💻 Useful Resources
* 🌍 **Website:** [exeris.eu](https://exeris.eu)
* 📩 **Contact:** [hello@exeris.eu](mailto:hello@exeris.eu)
* 💼 **LinkedIn:** [LinkedIn](https://www.linkedin.com/company/exeris-systems)
