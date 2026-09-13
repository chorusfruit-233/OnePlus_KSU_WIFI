.DEFAULT_GOAL := build
CONFIG ?= configs/oos16/OP13.json
KERNEL_TREE ?=
OUT ?= dist
.PHONY: check build clean
check:
	python3 scripts/check_config.py
build: check
	KERNEL_TREE="$(KERNEL_TREE)" scripts/build_lkm.sh "$(CONFIG)" "$(KERNEL_TREE)" "$(OUT)"
clean:
	python3 -c 'import shutil; shutil.rmtree("$(OUT)", ignore_errors=True)'
