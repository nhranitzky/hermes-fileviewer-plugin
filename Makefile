.PHONY: install clean

PLUGIN_NAME := fileviewer
PLUGIN_DIR := fileviewer

ifneq (,$(wildcard .env))
include .env
export
endif

PLUGIN_INSTALL_DIR ?= $(HOME)/.hermes/plugins/$(PLUGIN_NAME)

# Install the runtime plugin directory into PLUGIN_INSTALL_DIR from .env.
# Example .env:
#   PLUGIN_INSTALL_DIR=/opt/data/plugins/fileviewer
install:
	@command -v rsync >/dev/null 2>&1 || { echo "rsync is required for make install"; exit 127; }
	@test -n "$(PLUGIN_INSTALL_DIR)" || { echo "PLUGIN_INSTALL_DIR is empty"; exit 1; }
	@mkdir -p "$(dir $(PLUGIN_INSTALL_DIR))"
	@rsync -a --delete \
		--exclude '__pycache__/' \
		--exclude '*.pyc' \
		$(PLUGIN_DIR)/ "$(PLUGIN_INSTALL_DIR)/"
	@echo "Installed $(PLUGIN_DIR) -> $(PLUGIN_INSTALL_DIR)"

# Remove local caches.
clean:
	@rm -rf .pytest_cache __pycache__ tests/__pycache__ $(PLUGIN_DIR)/__pycache__ $(PLUGIN_DIR)/dashboard/__pycache__
