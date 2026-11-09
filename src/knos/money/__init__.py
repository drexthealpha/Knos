"""Knos's money engine: the one fee config (config/fees.yaml, read through `fees_config`), the agent tools that quote
and plan graduation and pre-orders (`agent`), the x402 endpoint (`x402`) and the revenue dashboard's data
(`revenue`). The vault itself is knos_pay's (knos.settle.v2.pay); graduation and splits are knos.graduation and
knos.splits. Devnet only: every fee is test money, and Knos's revenue is 0."""
