**AI Hub, build 154: creating an LLM provider on a fresh instance (lead from the build spec, not reproduced)**

The lead: on a fresh instance, creating an LLM provider fails with ERROR #26414 "No descriptor found for AI.LLM" until
`%ConfigStore.DescriptorManager.RebuildRegistry()` runs. Tried on a clean `irishealth-community:2026.3.0AI.154.0`
container (`2026.3.0AI (Build 154U)`): `##class(%AI.Provider).Create("anthropic", {"api_key":...,"model":...})` returned an
`%AI.Provider` with no rebuild. Not filed. One finding on the way: a settings key `apikey` is refused with
"unknown field `apikey`, expected one of `api_key`, `base_url`, `version`, `http_config`, `extra_config`", which is clear.
