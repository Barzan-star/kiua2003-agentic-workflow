# Agentic Workflow Course Project

The MET Norway probe reads `fixtures/met_hamar.json` when run with `--offline`.
This mode does not make a network request or change the fixture. Normal runs
reuse the HTTP cache at `out/met_hamar_cache.json` until its `Expires` time,
then refresh it from the MET Norway Locationforecast API. The generated probe
output remains at `out/probe.json`.

MET Norway forecast data is provided under the [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
license. The live API terms are documented at
https://api.met.no/doc/TermsOfService.
