
---

# 📘 Cilium Fundamentals & Lab Guide

This document outlines the core theoretical concepts of Cilium, explaining why it is the modern standard for Kubernetes networking, security, and observability.

## 🎯 What is Cilium?
Cilium is an open-source, cloud-native solution for providing, securing, and observing network connectivity between workloads. Unlike traditional Container Network Interfaces (CNIs) that rely on `iptables` or `IPVS`, Cilium is powered by **eBPF** (Extended Berkeley Packet Filter), enabling it to dynamically insert powerful security and networking logic directly into the Linux kernel.

---

## 🔄 The Paradigm Shift: Identity over IP
Traditional network policies rely on IP addresses, which are ephemeral in Kubernetes. When a Pod restarts, its IP changes, breaking static firewall rules.

* **The Old Way (IP-Based):** `"Allow traffic from 10.244.1.5 to 10.244.2.8"` → *Fails when Pods move or restart.*
* **The Cilium Way (Identity-Based):** `"Allow traffic from Pods with label `app=frontend` to `app=backend`"` → Cilium hashes these labels into a numeric **Security Identity** (e.g., `ID: 1001`). The kernel enforces policies based on this ID, meaning security travels with the Pod regardless of its IP or Node.

---

## ⚙️ Core Concepts

### 1. eBPF (The Data Plane)
* **What it is:** A Linux kernel technology that allows running sandboxed, verified programs directly in kernel space without modifying kernel source code or loading kernel modules.
* **Why it matters:** It eliminates the performance overhead of user-space to kernel-space context switching. Packet filtering, routing, and load balancing happen at **near-native kernel speed** with O(1) lookup complexity.

### 2. The Three Pillars of Cilium
1. **Networking:** Provides Pod-to-Pod connectivity, IP Address Management (IPAM), and cross-node routing (via VXLAN tunnels or Direct Routing/BGP).
2. **Security:** Enforces L3/L4 Kubernetes NetworkPolicies and L7 (HTTP/gRPC/Kafka) application-aware policies without requiring heavy sidecar proxies.
3. **Observability (Hubble):** Leverages kernel-level visibility to export real-time flow logs, metrics, and service dependency maps, making invisible network traffic completely transparent.

### 3. Kube-Proxy Replacement
* **The Problem:** `kube-proxy` manages Kubernetes Service load balancing by writing thousands of `iptables`/`IPVS` rules. At scale, this causes massive CPU overhead and `conntrack` table exhaustion.
* **The Cilium Solution:** Cilium can completely disable `kube-proxy` and handle Service load balancing (ClusterIP, NodePort, LoadBalancer) natively in eBPF. This enables features like **Direct Server Return (DSR)**, where response traffic routes directly to the client, bypassing the ingress node and cutting latency in half.

---

## 🛠️ This Lab's Configuration Explained

This lab deploys Cilium with a beginner-friendly, stable baseline using the following configuration:

```bash
cilium install --context kind-cilium-lab --version 1.20.2 \
  --set ipam.mode=kubernetes \
  --set routingMode=tunnel \
  --set tunnelProtocol=vxlan \
  --set kubeProxyReplacement=false \
  --wait
```

| Flag | What it does | Why we use it in this lab |
| :--- | :--- | :--- |
| `ipam.mode=kubernetes` | Delegates IP address allocation to the native Kubernetes `kube-controller-manager`. | Simplifies setup and ensures compatibility with standard Kind cluster networking. |
| `routingMode=tunnel` <br> `tunnelProtocol=vxlan` | Encapsulates Pod-to-Pod traffic in a VXLAN overlay across physical nodes. | Guarantees Pod connectivity even if the underlying host network doesn't know how to route Pod CIDRs. |
| `kubeProxyReplacement=false` | Keeps the traditional `kube-proxy` component running. | Provides a stable fallback while learning. *(Note: The next step in mastering Cilium is setting this to `strict` to unlock full eBPF performance).* |

---

## 🔍 Troubleshooting & Verification

* **Check Cilium Status:** `cilium status --context kind-cilium-lab`
* **View Live Network Flows:** `hubble observe`
* **View Dropped Traffic (Policy Denials):** `hubble observe --verdict DROPPED`
* **Inspect Traditional iptables Rules (for comparison):** 
  `docker exec -it cilium-lab-control-plane iptables -t nat -L -n -v`

---
