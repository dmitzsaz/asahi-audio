# SPDX-License-Identifier: MIT
# Copyright (C) 2023 The Asahi Linux Contributors

PREFIX ?= /usr/
DATA_DIR ?= $(PREFIX)/share/
LIBEXEC_DIR ?= $(PREFIX)/libexec
USER_UNIT_DIR ?= $(PREFIX)/lib/systemd/user

all: aliases

aliases: aliases-j274 aliases-j293 aliases-j314 aliases-j316 aliases-j375 aliases-j413 aliases-j415

aliases-j274:
	make -f $$PWD/Makefile -C firs/j274 graph-j473.json graph-j474.json

aliases-j375:
	make -f $$PWD/Makefile -C firs/j375 graph-j475.json graph-j575.json

aliases-j293:
	make -f $$PWD/Makefile -C firs/j293 graph-j493.json mic-j493.json

aliases-j314:
	make -f $$PWD/Makefile -C firs/j314 graph-j414.json mic-j414.json graph-j504.json mic-j504.json graph-j514.json mic-j514.json

aliases-j316:
	make -f $$PWD/Makefile -C firs/j316 graph-j416.json mic-j416.json graph-j516.json mic-j516.json

aliases-j413:
	make -f $$PWD/Makefile -C firs/j413 graph-j613.json mic-j613.json

aliases-j415:
	make -f $$PWD/Makefile -C firs/j415 graph-j615.json mic-j615.json

graph-%.json: graph.json
	sed -E "s/([^/][jJ])$$(basename "$$PWD" | tr -d j)/\1$(patsubst graph-j%.json,%,$@)/g" $< >$@

mic-%.json: mic.json
	sed -E "s/([^/][jJ])$$(basename "$$PWD" | tr -d j)/\1$(patsubst mic-j%.json,%,$@)/g" $< >$@

clean:
	rm -f firs/*/graph-*.json

core:
	install -dDm0755 $(DESTDIR)/$(DATA_DIR)/wireplumber/scripts/device/
	install -dDm0755 $(DESTDIR)/$(DATA_DIR)/wireplumber/scripts/node/
	install -dDm0755 $(DESTDIR)/$(DATA_DIR)/wireplumber/wireplumber.conf.d/
	install -dDm0755 $(DESTDIR)/$(DATA_DIR)/pipewire/pipewire.conf.d/
	install -dDm0755 $(DESTDIR)/$(DATA_DIR)/pipewire/pipewire-pulse.conf.d/
	install -pm0644 conf/wireplumber.conf $(DESTDIR)/$(DATA_DIR)/wireplumber/wireplumber.conf.d/99-asahi.conf
	install -pm0644 conf/asahi-lock-volume.lua $(DESTDIR)/$(DATA_DIR)/wireplumber/scripts/device/asahi-lock-volume.lua
	install -pm0644 conf/asahi-unplugged-routes.lua $(DESTDIR)/$(DATA_DIR)/wireplumber/scripts/device/asahi-unplugged-routes.lua
	install -pm0644 conf/asahi-restore-volume.lua $(DESTDIR)/$(DATA_DIR)/wireplumber/scripts/node/asahi-restore-volume.lua
	install -pm0644 conf/pipewire.conf $(DESTDIR)/$(DATA_DIR)/pipewire/pipewire.conf.d/99-asahi.conf
	install -pm0644 conf/pipewire.conf $(DESTDIR)/$(DATA_DIR)/pipewire/pipewire-pulse.conf.d/99-asahi.conf
	install -dDm0755 $(DESTDIR)/$(DATA_DIR)/asahi-audio/

j%: core
	install -dDm0755 $(DESTDIR)/$(DATA_DIR)/asahi-audio/$@/
	install -pm0644 -t $(DESTDIR)/$(DATA_DIR)/asahi-audio/$@/ $(wildcard firs/$@/*)


j704: j704-volume-eq

j704-volume-eq:
	install -dDm0755 $(DESTDIR)/$(LIBEXEC_DIR)/asahi-audio/
	install -pm0755 conf/j704-speaker-volume-eq $(DESTDIR)/$(LIBEXEC_DIR)/asahi-audio/
	install -dDm0755 $(DESTDIR)/$(USER_UNIT_DIR)/pipewire.service.wants/
	sed -e 's|@LIBEXEC_DIR@|$(LIBEXEC_DIR)|g' -e 's|@DATA_DIR@|$(DATA_DIR)|g' conf/j704-speaker-volume-eq.service.in >$(DESTDIR)/$(USER_UNIT_DIR)/j704-speaker-volume-eq.service
	chmod 0644 $(DESTDIR)/$(USER_UNIT_DIR)/j704-speaker-volume-eq.service
	ln -sfn ../j704-speaker-volume-eq.service $(DESTDIR)/$(USER_UNIT_DIR)/pipewire.service.wants/j704-speaker-volume-eq.service

install: aliases core j274 j293 j313 j314 j316 j413 j415 j375 j616 j700 j704

uninstall:
	rm -f $(DESTDIR)/$(LIBEXEC_DIR)/asahi-audio/j704-speaker-volume-eq
	rm -f $(DESTDIR)/$(USER_UNIT_DIR)/pipewire.service.wants/j704-speaker-volume-eq.service
	rm -f $(DESTDIR)/$(USER_UNIT_DIR)/j704-speaker-volume-eq.service
	rm -rf $(DESTDIR)/$(DATA_DIR)/asahi-audio/
	rm -rf $(DESTDIR)/$(DATA_DIR)/wireplumber/wireplumber.conf.d/99-asahi.conf
	rm -rf $(DESTDIR)/$(DATA_DIR)/wireplumber/scripts/device/asahi-limit-volume.lua
	rm -rf $(DESTDIR)/$(DATA_DIR)/wireplumber/scripts/node/asahi-restore-volume.lua
	rm -rf $(DESTDIR)/$(DATA_DIR)/pipewire/pipewire.conf.d/99-asahi.conf
	rm -rf $(DESTDIR)/$(DATA_DIR)/pipewire/pipewire-pulse.conf.d/99-asahi.conf

.PHONY: j704-volume-eq
