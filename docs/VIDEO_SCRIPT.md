# Demo video script (3:00 max)

Screen recording of the dashboard plus voice-over. No images of victims. Times are targets.

| Time | Screen | Voice-over |
|---|---|---|
| 0:00–0:15 | Title card over the Sentinel-2 after-image of the Bhote Koshi corridor | "On 26 August 2026 a glacier outburst sent a wall of water and debris down the Bhote Koshi–Trishuli valley in Nepal. Roads, bridges and phone lines went. Rescuers needed to know where the damage was and who was cut off." |
| 0:15–0:30 | Dashboard, empty. Pick the example "Syapru Besi", date 25 Aug 22:00 UTC | "WaterGuard takes an area and a flood date, and only free data: Sentinel-1 radar, Sentinel-2, the Copernicus DEM and OpenStreetMap as it was the day before." |
| 0:30–0:50 | Press **Map the flood**; progress bar steps (cached run finishes in seconds) | "Radar sees through monsoon cloud. We compare the first image after the flood with five earlier images from the same orbit track, and mask slopes the radar can't see. Where the sky was clear, Sentinel-2 shows stripped vegetation and fresh sediment." |
| 0:50–1:10 | Impact layer on; toggle Sentinel-2 before/after; zoom to the confluence | "The DEM tells us where a surge can reach. Change on the valley floor that connects to the river becomes the impact map: 174 hectares here." |
| 1:10–1:35 | Buildings hit, roads cut, bridges; click a red bridge | "Overlaying pre-event OpenStreetMap: 227 buildings likely hit, 11 km of road in the impact zone and 8 bridges likely gone, including the main road through Syabru Bensi." |
| 1:35–1:55 | Cut-off tab, Syabru Bensi in red; click it | "Then the road network: we delete the washed-out segments and bridges and ask who can still reach a town, a health post or the road out. Syabru Bensi, about 400 buildings, has no road link left." |
| 1:55–2:25 | Ask tab: "Which villages are cut off?" then "कुन कुन पुल भत्किए?"; point at the "✓ numbers checked" line | "The copilot answers in English or Nepali, but it has no numbers of its own. It reads the maps through tools, and a verifier checks every number in its answer against them. Anything unverified is masked." |
| 2:25–2:40 | Report tab: open the Nepali one-pager; then Trace flood path from Timure | "One click gives a one-page situation report in English or Nepali. And from any point upstream, we trace the flood path and list the villages in its way." |
| 2:40–2:55 | Validation table (README/report) | "Against the official Copernicus EMS maps, on two areas we never tuned on, we reach F1 0.92 and 0.88, and at least nine in ten of the buildings EMS rated destroyed sit on our map. On a fake date and an untouched valley, it maps almost nothing." |
| 2:55–3:00 | End card: limitations line + attributions | "Satellites revisit every few days, so this maps damage, it can't warn. Educational prototype. Contains modified Copernicus Sentinel data 2026." |

Recording tips: run the example areas once before recording so they load from cache. Use 1600×900 browser, dark basemap, zoom ~13 on the confluence.
