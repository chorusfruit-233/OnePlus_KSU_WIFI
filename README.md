# OnePlus_KSU_WIFI

按 [OnePlus_ReSukiSU_SUSFS](../OnePlus_ReSukiSU_SUSFS) 的设备矩阵组织，为 OnePlus 设备内核树中未启用的无线网卡驱动构建 KernelSU 模块。每个设备产出一个 ZIP，模块内包含该设备编译出的 `.ko`、目标 `kernel.release`、`Module.symvers` 和配置快照；`service.sh` 在启动时通过 `/data/adb/ksud insmod` 加载驱动。

## ABI 前提

必须使用与手机当前运行内核完全对应的源码提交、`.config`、`Module.symvers`、工具链和 `kernelrelease`。脚本只把选定的无线驱动从 `n` 改为 `m`，不会修改 `LOCALVERSION`、LTO、SUSFS 或其他 ABI 设置。`modules_prepare` 不能替代完整的 `Module.symvers`。模块签名、CONFIG_MODVERSIONS、内核版本或导出符号不匹配时应停止安装。

## 目录

- `configs/oosXX/*.json`：设备、内核目录、defconfig、编译器和无线 profile。
- `manifests/oosXX/*.xml`：沿用参考项目的 OnePlus 源码 manifest。
- `profiles/wifi-drivers.json`：无线驱动 Kconfig、产物和固件族。
- `scripts/build_lkm.sh`：基于现有内核树构建并打包单设备模块。
- `module-template/service.sh`：启动时校验 `uname -r` 后调用 `ksud insmod`。
- `.github/workflows/mirror-toolchains.yml`：从全部 manifest 收集工具链 revision，写入 `toolchain-cache` Release。
- `scripts/mirror_toolchains.py`：生成工具链镜像矩阵。

CI 的 `build.yml` 使用 `actions/cache` 保存每设备 ccache（默认 8 GiB），缓存键包含设备配置和无线 profile；工具链同步优先读取 `TOOLCHAIN_CACHE_URL`，因此可由 `mirror-toolchains.yml` 预热。`ccache` 缓存会在 job 结束时由 Actions 自动保存。

clang 预编译仓库同时存放历次发布的多个 clang 版本，整包普遍超过 GitHub Release 单个 asset 的 2 GiB 上限，因此镜像按 `(revision, clang-rXXXXXX)` 切成独立条目：workflow 只保留设备 `compiler` 指向的那个子目录，`sync_manifest.py --config` 按同一子目录名取用。下载顺序为 `clang-<rev>-<子目录>.tar.gz` → `clang-<rev>.tar.gz`（整包，兼容旧缓存）→ CodeLinaro `git clone`。build-tools 和 rust 体积较小，仍按整包镜像。

## 使用

```sh
python3 scripts/check_config.py
make CONFIG=configs/oos16/OP13.json KERNEL_TREE=/path/to/checked-out/kernel
# 仅检查全部设备矩阵
make check
```

构建前在目标树中准备好 `.config`、完整 `Module.symvers` 和已生成的精确 `kernel.release`。可用 `KERNEL_BUILD_DIR`、`KERNEL_CONFIG`、`KERNEL_SYMVERS` 指向单独的目标构建目录；需要打包现有依赖模块时设置 `KERNEL_MODULES_DIR`。固件不会从内核仓库自动复制；根据 profile 的 `firmware` 列表把匹配版本放入模块的 `firmware/` 目录，并确保系统允许模块访问该路径。`firmware_policy=warn` 只提示缺失固件，驱动能否工作仍需在设备上验证。

项目已同步参考项目的全部 158 个设备配置和 158 个 manifest（OOS14/OOS15/OOS16）。每个配置都包含 `kernel_dir`、`defconfig`、`wifi_drivers`、`expected_release_prefix` 等 LKM 构建字段。所有 158 个设备都额外启用 `usb-wifi` 候选集合，构建时按目标内核实际存在的 Kconfig 和源码自动筛选；不存在的候选会跳过，不会阻断该设备。Qualcomm 设备默认选择 ath11k/ath12k，联发科设备默认选择 mt76-usb；构建前必须根据目标源码的 Kconfig 和实际无线芯片复核 profile，缺少驱动源码时构建会明确失败。可按同样格式添加设备和 USB 无线 profile（`rtl8xxxu` 等）。
