# OnePlus KSU WiFi

KernelSU-enabled kernel builds for OnePlus devices, with **working WiFi** as the
primary goal.

[![KernelSU](https://img.shields.io/badge/KernelSU-Supported-green)](https://kernelsu.org/)

> **Status: scaffold.** This repository was just initialised. Build scripts,
> device manifests and per-device configuration are not committed yet — the
> README will be filled in as the project takes shape.

## Overview

Recent OnePlus devices boot GKI/OGKI kernels in which the wireless stack is
delivered as loadable kernel modules rather than being linked into the kernel
image. Keeping KernelSU and WiFi working at the same time therefore comes down
to building, matching and loading the correct module payload for each KMI.

This repository collects the OnePlus build configuration for that setup.

## Related projects

| Project | Purpose |
|---------|---------|
| [GKI-WiFi-KSU](https://github.com/chorusfruit-233/GKI-WiFi-KSU) | Prebuilt WiFi LKM payloads shipped as a KernelSU module |
| [OnePlus_SDM845_ReSukiSU_SUSFS](https://github.com/chorusfruit-233/OnePlus_SDM845_ReSukiSU_SUSFS) | Automated SDM845 ReSukiSU + SUSFS kernel / AnyKernel3 builder |
| [Wild Kernels · OnePlus_KernelSU_SUSFS](https://github.com/WildKernels/OnePlus_KernelSU_SUSFS) | Upstream OnePlus KernelSU + SUSFS kernel builds |

## Supported devices

To be documented.

## Building

To be documented.

## Disclaimer

Flashing a custom kernel is done at your own risk. Back up your data and make
sure you understand what you are flashing before you start. The author is not
responsible for bricked devices, damaged hardware, or any other consequences.

## License

To be decided.
