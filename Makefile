.PHONY: dist install clean

PLUGIN_NAME := filebrowser
VERSION := 0.1.0
PLUGIN_DIR := filebrowser
DIST_DIR := dist
BUILD_DIR := .build/$(PLUGIN_NAME)
TAR_FILE := $(DIST_DIR)/$(PLUGIN_NAME)-$(VERSION).tar.gz

ifneq (,$(wildcard .env))
include .env
export
endif

PLUGIN_INSTALL_DIR ?= $(HOME)/.hermes/plugins/$(PLUGIN_NAME)

# Build an installable plugin archive using tar.
# Included: runtime plugin files under filebrowser/ plus root README.md.
# Excluded: tests, caches, SPEC.md, Makefile, .env, and other development-only files.
dist:
	@rm -rf .build $(DIST_DIR)
	@mkdir -p $(BUILD_DIR) $(DIST_DIR)
	@cp -a $(PLUGIN_DIR)/. $(BUILD_DIR)/
	@find $(BUILD_DIR) -type d -name '__pycache__' -prune -exec rm -rf {} +
	@find $(BUILD_DIR) -type f -name '*.pyc' -delete
	@cp README.md $(BUILD_DIR)/README.md
	@tar -C .build -czf $(TAR_FILE) $(PLUGIN_NAME)
	@rm -rf .build
	@echo $(TAR_FILE)

# Install the runtime plugin directory into PLUGIN_INSTALL_DIR from .env.
# Example .env:
#   PLUGIN_INSTALL_DIR=/opt/data/plugins/filebrowser
install:
	@command -v rsync >/dev/null 2>&1 || { echo "rsync is required for make install"; exit 127; }
	@test -n "$(PLUGIN_INSTALL_DIR)" || { echo "PLUGIN_INSTALL_DIR is empty"; exit 1; }
	@mkdir -p "$(dir $(PLUGIN_INSTALL_DIR))"
	@rsync -a --delete \
		--exclude '__pycache__/' \
		--exclude '*.pyc' \
		$(PLUGIN_DIR)/ "$(PLUGIN_INSTALL_DIR)/"
	@echo "Installed $(PLUGIN_DIR) -> $(PLUGIN_INSTALL_DIR)"

# Remove generated artifacts and local caches.
clean:
	@rm -rf $(DIST_DIR) .build .pytest_cache __pycache__ tests/__pycache__ $(PLUGIN_DIR)/__pycache__ $(PLUGIN_DIR)/dashboard/__pycache__
