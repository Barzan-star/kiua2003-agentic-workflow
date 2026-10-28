---
name: met-api
description: "Use when calling api.met.no or working with fixtures/met_hamar.json: request identification, HTTP caching, and forecast JSON fields."
---

# MET API and fixture instructions

- Use HTTPS for all API requests.
- Identify live API requests with an application User-Agent and a project website or repository reference.
- Cache responses locally. Do not repeat requests before the response's `Expires` time.
- When refreshing, send `If-Modified-Since` using the exact saved `Last-Modified` value.
- Reuse cached data after a `304` response.
- In offline mode, use the saved fixture without making network requests or refreshing it.
- Read timestamps from `properties.timeseries[].time`.
- Read temperatures in Celsius from `properties.timeseries[].data.instant.details.air_temperature`.
- Treat fixture timestamps as saved historical data, not today's forecast.
- Check the implementation before claiming that HTTP caching is implemented.
- Attribute MET Norway data under CC BY 4.0.
- Source reference: https://api.met.no/doc/TermsOfService
