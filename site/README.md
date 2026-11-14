# Rio Grande Outlook — opening site

The opening page for the Rio Grande Farm Drought Outlook. It has four parts:

1. **Title page.** The river's name cut out of the canyon photograph, the river's
   real course drawn beside it, and one line of its recent history that changes
   every few seconds. On scroll the map opens over it as a circle growing out of
   the letter I.
2. **The journey.** One pinned screen, 13 chapters. Nine stops from the
   headwaters to the Gulf, each naming one pressure on the river and who feels
   it, with its source. Then four steps back: the 31 counties, the problem, the
   aid trigger and the idea.
3. **The method.** Set like a research paper: ten numbered sections, ruled
   tables and two figures.
4. **The solution.** An empty, reserved section. Nothing is in it yet, on purpose.

The button at the top right opens the tool itself (see "Before you publish").

## Run it

```bash
npm install
```

```bash
npm run dev
```

Then open http://localhost:5183.

```bash
npm run build
```

writes the finished site to `dist/`.

## Where things are

| Path | What it is |
|---|---|
| `src/content.js` | **Every word on the page**, including every table. Edit text here and nowhere else |
| `src/components/journey/Hero.jsx` | The title page |
| `src/components/journey/Journey.jsx` | The scroll journey: map, camera, chapters |
| `src/components/journey/Widgets.jsx` | The small graphics under some chapters |
| `src/components/paper/Paper.jsx` | The method, laid out from `paper` in `content.js` |
| `src/components/paper/Figures.jsx` | Figure 1 (outcome windows), Figure 2 (time splits), the transfer table |
| `src/components/Solution.jsx` | The reserved, empty Solution section |
| `src/components/Closing.jsx` | Final call to action, credits, footer |
| `src/index.css` | Colours, type and all styling |
| `src/data/map.json` | The river, tributaries, states, counties, stations. Generated; do not edit |
| `scripts/build-map.mjs` | Builds `map.json` |
| `public/images/canyon.jpg` | The photograph |

To add a stop to the journey: add a station (id and coordinates) to
`scripts/build-map.mjs`, rebuild the map, and add a chapter with the same `id`
to `journey.chapters` in `content.js`, in river order.

## The map is real

`scripts/build-map.mjs` builds the map from Natural Earth's river centrelines and
U.S. Census county shapes (the `us-atlas` package). A county is included when its
centre is within 50 km of the river, the same rule the research uses. That rule
gives 31 counties (8 in Colorado, 9 in New Mexico, 14 in Texas), which matches
the research. The Pecos, the Conchos and Mexico's San Juan come from the same
river file; Mexico's outline comes from the `world-atlas` package. The river
file is not committed (7 MB): download it once, then rebuild.

```bash
curl -L -o scripts/cache/rivers.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_rivers_lake_centerlines.geojson
```


```bash
node scripts/build-map.mjs
```

## Before you publish

Everything below is in `src/content.js` unless noted.

- [ ] `site.product.url`: the address of the tool. While it is empty, the button
      shows a "being introduced separately" note instead of going anywhere.
- [ ] **Provisional figures.** Two places use numbers from the Nov 14 test runs:
      the **57%** in the journey (`journey.chapters` → `problem` → `stat`) and
      the last column of the transfer table (`paper` → `transfer` → `rows`).
      Both describe the data, not a model, and both are labelled provisional on
      the page. Replace them with final figures or remove them.
- [ ] **River facts.** Each journey chapter cites its source. The facts were
      checked by web search on Nov 14, 2026, not against the original documents.
      Read each source before you publish. The San Luis Valley aquifer figure
      ("more than a million acre-feet below its 1976 benchmark") is the one to
      check first: the linked article may not be where that number came from.
- [ ] **Solution section.** `src/components/Solution.jsx` is an empty frame.
- [ ] `footer.team` and `footer.contact`: both are `[BRACKETS]` placeholders.
- [ ] `footer.credits`: the photograph's photographer and licence are a placeholder.
      **Do not publish until you know you may use the photo.**
- [ ] The photo is 553 x 715 px. It is sharp in its frame but soft once it fills
      the screen. A larger original at `public/images/canyon.jpg` fixes that.
- [ ] Check the wording under "What this work does not claim" against the final
      write-up.

## What has and has not been checked

- Scrolled the whole journey forward and then backward in headless Chrome at
  1440 x 900, sampling every frame: no camera jumps, no console errors, no
  failed requests, and the title page comes back intact at the top.
- Looked at by eye at 1440 x 900 and 375 x 812: title page, journey chapters,
  method sections, the Solution shell. No horizontal page scroll.
- Not checked: 768 px wide after the redesign, Firefox and Safari, a real phone,
  a Lighthouse run, a screen reader.
- There are no automated tests in the repository.
- On a phone the method's tables scroll sideways inside their own frame.
- With "reduce motion" turned on, the map still follows the scroll, but the
  camera does not ease, the title does not swell, and the water droplets stop.

## Deploy

**Vercel:** import the repository at vercel.com/new. It detects Vite; the build
command is `npm run build` and the output folder is `dist`.

**Netlify:** "Add new site" → import the repository. Build command `npm run build`,
publish directory `dist`.

## Credits

See the footer of the site (`footer.credits` in `src/content.js`).
