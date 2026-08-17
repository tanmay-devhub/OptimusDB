# Extend postgres:16 with the HypoPG extension.
#
# HypoPG lets us CREATE hypothetical indexes that the planner considers
# during EXPLAIN, without ever writing a physical index. That is the
# primitive OptimusDB's mode="hypothetical" leans on for production-scale
# databases where a real CREATE INDEX on a 500 GB table is not on the
# table.
#
# The package name follows Debian's postgres-<major>-<ext> convention.
FROM postgres:16

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-hypopg \
    && rm -rf /var/lib/apt/lists/*
