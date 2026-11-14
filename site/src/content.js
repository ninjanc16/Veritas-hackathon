// Every word on the page lives here. Edit this file; the components only lay it out.
// Anything in [BRACKETS] is a placeholder for you to fill in.
//
// Two rules this file keeps on purpose:
// 1. No model results. Results live in the tool and come from metrics.json.
//    The method section describes the DESIGN of the study, which does not change.
// 2. Every fact about the river carries its source (`source` on each chapter).
//    Two figures are marked provisional; search this file for "provisional".

export const site = {
  name: 'Rio Grande Outlook',
  fullName: 'Rio Grande Farm Drought Outlook',
  nav: [
    ['The river', '#top'],
    ['Method', '#method'],
    ['Solution', '#solution'],
  ],
  // Put the tool's address here when it is ready. While empty, the button says so.
  product: {
    label: 'Open the outlook',
    url: '',
    pending: 'The tool is being introduced separately. This button will open it.',
  },
}

export const hero = {
  label: 'A drought outlook · 31 farm counties · Colorado, New Mexico, Texas',
  word: ['RIO', 'GRANDE'],
  script: 'read ahead.',
  hook: 'Along this river, drought is not a surprise. It is the normal risk. We set out to see it coming.',
  // The lines that rotate on the title page. Each is sourced in a chapter below.
  datelines: [
    ['2001', 'The river fails to reach the sea.'],
    ['2022', 'Five miles of riverbed run dry in Albuquerque.'],
    ['2024', 'The last sugar mill in Texas closes for lack of water.'],
    ['2026', 'Elephant Butte reservoir falls to 1.4% of capacity.'],
  ],
  cue: 'Scroll to travel the river',
  photoAlt: 'The Rio Grande winding through a sandstone canyon, with magenta cactus flowers in the foreground.',
}

// The scroll journey. The first nine chapters are places on the river, in order
// from source to sea; `id` ties each to a point in src/data/map.json. The last
// four step back to look at the counties and the idea.
//   pressure: the short name added to the "pressures on the river" list
//   affects:  who feels it
//   ghost:    the large word behind the map
export const journey = {
  mapLabel:
    'Animated map of the Rio Grande from its headwaters in Colorado, through New Mexico, along the Texas–Mexico border to the Gulf, with its tributaries, reservoirs and the 31 farm counties along it.',
  pressuresTitle: 'Pressures on the river',
  affectsLabel: 'Who feels it',
  sourceLabel: 'Source',
  reached: 'counties reached',
  dryLabel: 'Forgotten Reach · often dry',
  chapters: [
    {
      id: 'source',
      kicker: 'Headwaters · San Juan Mountains, Colorado',
      title: 'It starts as snow.',
      body: [
        'The Rio Grande begins high in the San Juan Mountains. What falls here in winter decides how much river there is in summer.',
        'In spring 2026 the three river states opened the season facing drought and a low snowpack.',
      ],
      pressure: 'Low snowpack',
      affects: 'Everyone downstream',
      ghost: 'SNOW',
      source: ['Source NM, April 2026', 'https://sourcenm.com/2026/04/22/facing-drought-and-low-snowpack-rio-grande-states-expect-a-challenging-year/'],
    },
    {
      id: 'valley',
      kicker: 'San Luis Valley, Colorado',
      title: 'The farms pump what the river cannot give.',
      body: [
        'Around Alamosa, irrigated farms draw on the aquifer under the valley. It has fallen more than a million acre-feet below its 1976 benchmark.',
        'Colorado has warned that wells could be shut off if the aquifer is not restored.',
      ],
      pressure: 'Falling groundwater',
      affects: 'Farm families of the valley',
      ghost: 'GROUNDWATER',
      source: ['Water Desk', 'https://waterdesk.org/2020/08/san-luis-valley-farmers-rio-grande-river'],
    },
    {
      id: 'middle',
      kicker: 'Albuquerque, New Mexico',
      title: 'In 2022, the river stopped.',
      body: [
        'In the last week of July 2022, five miles of the Rio Grande ran dry in Albuquerque, for the first time in 40 years.',
        'Crews netted endangered Rio Grande silvery minnows out of the last pools. The fish survives in less than 7% of its historical range.',
      ],
      pressure: 'A drying channel',
      affects: 'A city, its farms and an endangered fish',
      ghost: 'DRY BED',
      source: ['NASA Earth Observatory; Associated Press', 'https://earthobservatory.nasa.gov/images/150244/rio-grande-runs-dry-then-wet'],
    },
    {
      id: 'butte',
      kicker: 'Elephant Butte Reservoir, New Mexico',
      title: 'The savings account is nearly empty.',
      body: [
        'Elephant Butte stores the river for the farms below it. In the summer of 2026 it fell to about 1.4% of capacity, its lowest level since 1971.',
        'A 1938 compact divides the river among Colorado, New Mexico and Texas. Texas has taken New Mexico to court over its share.',
      ],
      pressure: 'Empty storage, a contested compact',
      affects: 'Irrigators in New Mexico and Texas',
      ghost: '1.4%',
      source: ['NASA Earth Observatory', 'https://science.nasa.gov/earth/earth-observatory/elephant-butte-reservoir-runs-low/'],
    },
    {
      id: 'pass',
      kicker: 'El Paso · Ciudad Juárez',
      title: 'One river, two countries.',
      body: [
        'From here to the sea, the Rio Grande is the border between the United States and Mexico.',
        'Just downstream, near Fort Quitman, the U.S. Geological Survey estimates the river carries about 5% of its natural flow.',
      ],
      pressure: 'Shared by two nations',
      affects: 'Two cities and the farms around them',
      ghost: 'BORDER',
      source: ['Inside Climate News, citing USGS', 'https://insideclimatenews.org/news/23102024/holding-out-hope-drying-rio-grande/'],
    },
    {
      id: 'reach',
      kicker: 'The Forgotten Reach, Texas',
      title: 'Then it nearly disappears.',
      body: [
        'Between Fort Quitman and Presidio the river holds so little water that the stretch is known as the Forgotten Reach.',
        'The National Park Service notes that below Fort Quitman the river no longer has a defined channel.',
      ],
      pressure: 'A river without water',
      affects: 'Communities along the desert border',
      ghost: 'FORGOTTEN',
      source: ['National Park Service, Big Bend', 'https://www.nps.gov/bibe/learn/nature/waterflow.htm'],
    },
    {
      id: 'conchos',
      kicker: 'Presidio · Ojinaga',
      title: 'A river from Mexico brings it back.',
      body: [
        'At Presidio the Rio Conchos joins from Chihuahua. It is the main source of water for the river below here.',
        'Under a 1944 treaty, Mexico owes the United States 1.75 million acre-feet from its tributaries every five years. In drought, farmers on the Conchos have none to spare.',
      ],
      pressure: 'Dependence on a treaty',
      affects: 'Farmers on both sides of the border',
      ghost: 'CONCHOS',
      source: ['Texas Observer; Texas Public Radio', 'https://www.texasobserver.org/big-bend-rio-grande-dry-water/'],
    },
    {
      id: 'lower',
      kicker: 'Lower Rio Grande Valley, Texas',
      title: 'The last farms on the river.',
      body: [
        'In 2024 the last sugar mill in Texas closed after 51 years, citing the lack of irrigation water. About 500 jobs went with it.',
        'Growers in the valley are now asking which crop is next.',
      ],
      pressure: 'Crops without water',
      affects: 'Growers and mill workers of the valley',
      ghost: 'HARVEST',
      source: ['Texas Public Radio, February 2024', 'https://www.tpr.org/environment/2024-02-26/the-last-sugar-mill-in-texas-shuts-down-because-of-ongoing-water-issues-with-mexico'],
    },
    {
      id: 'gulf',
      kicker: 'Boca Chica · Gulf of Mexico',
      title: 'Some years, it does not arrive.',
      body: [
        'In 2001 a sandbar closed the river’s mouth. For the first time in recorded history, the Rio Grande failed to reach the sea.',
      ],
      pressure: 'A river that ends early',
      affects: 'The delta and its estuary',
      ghost: 'THE GULF',
      source: ['Christian Science Monitor, May 2001', 'https://csmonitor.com/2001/0521/p3s1.html'],
    },
    {
      id: 'counties',
      kicker: 'The people in its path',
      title: 'Thirty-one farm counties.',
      body: [
        'Every county whose centre lies within 50 km of the river. Ranchers graze cattle here, and farmers irrigate from the river. All of those pressures arrive in these places as one thing: drought.',
      ],
      widget: 'counties',
      breakdown: [
        [8, 'Colorado'],
        [9, 'New Mexico'],
        [14, 'Texas'],
      ],
      ghost: '31',
    },
    {
      id: 'problem',
      kicker: 'The problem',
      title: 'Here, drought is the normal risk.',
      body: [
        'Each week the U.S. Drought Monitor maps where drought is now. It does not say what is likely next, county by county.',
      ],
      widget: 'scale',
      // A description of the data, not a model result. Still provisional: replace
      // it with the final figure, or delete `stat` to hide it.
      stat: {
        value: '57%',
        text: 'of county-weeks here since 2019 were followed by severe drought within four weeks.',
        tag: 'Provisional: from our Nov 14 test runs',
      },
      ghost: '57%',
    },
    {
      id: 'trigger',
      kicker: 'Why “severe” is the line',
      title: 'Eight weeks changes the decision.',
      body: [
        'Eight straight weeks of severe drought in a county, during the grazing period, can open a payment under USDA’s Livestock Forage Disaster Program.',
        'That is the level where plans change: sell cattle or buy hay, plant a field or leave it fallow.',
      ],
      widget: 'eight',
      ghost: '8 WEEKS',
    },
    {
      id: 'idea',
      kicker: 'The idea',
      title: 'Read the river ahead.',
      body: ['From 26 years of weekly drought maps, three forecasts for every county. The Rio Grande first; then the same method on four other rivers.'],
      widget: 'horizons',
      horizons: [
        ['4 weeks', 'An alert. Is severe drought likely here soon?'],
        ['6 months', 'An outlook. Is an eight-week run likely this season?'],
        ['12 months', 'A planning range. About how many weeks next year?'],
      ],
      methodLink: 'Read the method',
      ghost: 'AHEAD',
    },
  ],
  scale: [
    ['None', false],
    ['D0', false],
    ['D1', false],
    ['D2', true],
    ['D3', true],
    ['D4', true],
  ],
  scaleNote: 'U.S. Drought Monitor classes. D2 and above is severe drought.',
}

// ---------------------------------------------------------------------------
// The method, set like a research paper. Tables are plain data: `head` is the
// header row, `rows` the body. Keep cells short; long text goes in `notes`.
// ---------------------------------------------------------------------------
export const paper = {
  eyebrow: 'Method',
  title: 'Forecasting severe drought for 31 Rio Grande counties at three horizons',
  abstract:
    'We train three random forests on the weekly county record of the U.S. Drought Monitor: a 4-week alert, a 6-month outlook for an eight-week run of severe drought, and a 12-month estimate of weeks in severe drought. Every model is trained on earlier years and tested on later ones, scored against persistence, climatology and tougher simple rules, and then applied unchanged to four other rivers. This page documents the design. Results are reported in the tool.',
  sections: [
    {
      id: 'glance',
      title: 'Study at a glance',
      facts: [
        ['Location', 'Rio Grande. 31 counties: 8 in Colorado, 9 in New Mexico, 14 in Texas'],
        ['Selection rule', 'County centre within 50 km of the river’s main line'],
        ['Unit of analysis', 'County-week (alert); county-month (outlooks)'],
        ['Record', 'U.S. Drought Monitor, worst class in the county, weekly from 4 January 2000'],
        ['Event', 'Severe drought: class D2 or worse'],
        ['Models', 'Two random forest classifiers and one regressor, trained on Rio Grande counties only'],
        ['Evaluation', 'Later years held out. Cost, precision, recall and mean absolute error'],
        ['Compared with', 'Persistence, climatology and three tougher simple rules'],
        ['Transfer test', 'Applied unchanged to 405 counties on the Colorado, Missouri, Mississippi and Ohio'],
      ],
    },
    {
      id: 'data',
      title: 'Data',
      table: {
        head: ['', 'Dataset', 'Used for', 'Coverage', 'Licence', 'Status'],
        rows: [
          ['D1', 'County drought history (U.S. Drought Monitor; archive by the Montana Climate Office)', 'Every label and every history input', 'Weekly, Jan 2000 to present. 3,203 of 3,251 counties have a complete record', 'CC0', 'In use'],
          ['D2', 'River centrelines (Natural Earth); county shapes (U.S. Census)', 'Choosing river counties; county centres', 'Contiguous United States', 'Public domain', 'In use'],
          ['D3', 'Oceanic Niño Index (NOAA Climate Prediction Center)', 'Long-lead input to the 6-month outlook', 'Three-month seasons, 1998 to 2026', 'Public domain', 'In use; tested with and without'],
          ['D4', 'Daily river flow at Rio Grande gauges (USGS)', 'Candidate long-lead input', 'Daily mean flow from 2000', 'Public domain', 'Ablation only'],
          ['D5', 'Snowpack, upper Rio Grande (NRCS SNOTEL)', 'Candidate long-lead input', 'Not yet assembled', 'Public domain', 'Not tested'],
        ],
      },
      notes: [
        'Only counties with a complete weekly record are kept, so every county has the same history.',
        'A copy of each raw file is committed with the code so that results can be reproduced.',
      ],
    },
    {
      id: 'targets',
      title: 'Targets',
      figure: 'horizons',
      table: {
        head: ['Product', 'Question, per county', 'Horizon', 'Issued', 'Model', 'Reported as'],
        rows: [
          ['4-week alert', 'Will the worst class reach D2 or worse in any of the next 4 weeks?', '4 weeks', 'Weekly', 'Classifier', 'Tier: Low, Watch, Warning'],
          ['6-month outlook', 'Will the next 26 weeks contain 8 or more consecutive weeks at D2 or worse?', '26 weeks', 'Monthly', 'Classifier', 'Probability, beside the county’s usual rate'],
          ['12-month outlook', 'How many of the next 52 weeks will be at D2 or worse?', '52 weeks', 'Monthly', 'Regressor', 'Weeks, with typical error'],
        ],
      },
      notes: [
        'Eight consecutive weeks at D2 is the threshold used by USDA’s Livestock Forage Disaster Program. The grazing period is not modelled.',
        'An outcome window always begins the week after the forecast is issued.',
      ],
      // Shown under the 52-week figure, one line per product.
      captions: {
        alert: 'Any one week at D2 or worse inside the next four makes the outcome positive.',
        season: 'Eight consecutive weeks at D2 or worse, anywhere inside the next 26, make the outcome positive.',
        year: 'The outcome is a count: the number of weeks at D2 or worse in the next 52.',
      },
      figureNote: 'Each cell is one week ahead. Filled cells illustrate the target; they are not data.',
    },
    {
      id: 'features',
      title: 'Inputs',
      table: {
        head: ['Set', 'n', 'Inputs', 'Used by'],
        rows: [
          ['H · history', '24', 'Class now and 1, 2, 4, 8, 12, 26 and 52 weeks ago. 4- and 8-week change. 12-, 26- and 52-week maximum. 12- and 26-week mean. Weeks at the current class. Weeks since the last D2. Counties within 150 km: mean class, maximum class, share in D2, 4-week change, neighbour mean minus own class. Sine and cosine of week of year', 'All three products'],
          ['L · long memory', '5', 'Share of the last 52, 104 and 156 weeks at D2 or worse. Share of all weeks so far at D2 or worse. Mean class of the river’s counties now', 'Both outlooks'],
          ['E · ENSO', '5', 'Latest index value, its three-season change, and its mean, minimum and maximum over the last 12 seasons', '6-month outlook'],
          ['F · flow', '2', 'Per gauge: 90-day and 365-day mean flow as a percentile of the same calendar window in the training years. Each county uses its nearest gauge', 'Ablation only'],
        ],
      },
      notes: [
        'Latitude and longitude are deliberately excluded, so that a model trained on one river can be applied to another.',
        'An ENSO season is used only if it ended before the month the forecast is issued.',
        'The first 156 weeks are dropped from the outlooks, because the long-memory inputs need three years of history.',
      ],
    },
    {
      id: 'models',
      title: 'Models',
      table: {
        mono: [1, 2, 3, 4, 5],
        head: ['Product', 'Trees', 'Max depth', 'Min leaf', 'Max features', 'Class weight', 'Inputs', 'Trained on'],
        rows: [
          ['4-week alert', '100', '12', '100', 'sqrt', 'balanced_subsample', 'H', 'Rio Grande, 2000 to 2014'],
          ['6-month outlook', '80', '10', '20', 'sqrt', 'none', 'H + L + E', 'Rio Grande, forward chaining'],
          ['12-month outlook', '80', '10', '20', 'sqrt', 'n/a', 'H + L', 'Rio Grande, forward chaining'],
        ],
      },
      notes: [
        'scikit-learn RandomForestClassifier and RandomForestRegressor, random_state = 0. Settings were fixed and written down before the final run.',
        'The 4-week score is a risk score, not a calibrated probability, because of class weighting. The 6-month output is unweighted.',
        'A forest cannot predict beyond what it has seen. A drought deeper than any in the training years is a known failure case.',
      ],
    },
    {
      id: 'splits',
      title: 'Train on the past, test on the future',
      figure: 'splits',
      splits: {
        alert: {
          name: 'Figure 2a. 4-week alert: one block split',
          legend: [
            ['train', 'Train, 2000 to 2014'],
            ['val', 'Choose the alarm threshold, 2015 to 2018'],
            ['test', 'Test, 2019 onward. Reported once'],
          ],
        },
        outlook: {
          name: 'Figure 2b. Outlooks: forward chaining',
          sliderLabel: 'Test year',
          legend: [
            ['warm', 'Warm-up for long-memory inputs'],
            ['train', 'Train'],
            ['gap', 'Excluded: outcome not yet known'],
            ['test', 'Test year'],
          ],
        },
      },
      notes: [
        'For each test year from 2008 to 2025, the outlook models are trained only on forecasts whose outcome was already known before that year began. Move the slider: the model never sees the year it is tested on.',
        'No split is random. A random split would let a model learn a drought from its own middle weeks.',
      ],
    },
    {
      id: 'scoring',
      title: 'Baselines and scoring',
      formula: ['cost', '=', '3 × misses', '+', 'false alarms'],
      table: {
        head: ['Product', 'Baselines it must beat', 'Scored by'],
        rows: [
          ['4-week alert', 'Persistence (in D2 now). D1 or worse now. Worsening (in D2 now, or in D1 and worse than 4 weeks ago). Calendar (the river’s usual rate for the week of year). Logistic regression, as a comparison model', 'Cost; precision and recall, separately'],
          ['6-month outlook', 'Persistence. D1 or worse now. Usual for this county. Always warn. Never warn', 'Cost at a threshold of 0.25; precision and recall; Brier score by year'],
          ['12-month outlook', 'Same as now (52 if in D2, else 0). Same as the last 52 weeks. Usual for this county', 'Mean absolute error, in weeks'],
        ],
      },
      notes: [
        'One miss is counted as three false alarms. That ratio is our assumption, so results are also reported at 2, 5 and 10.',
        'The 0.25 threshold is not tuned: it is the break-even point when a miss costs three false alarms.',
        'A product passes only if it beats the cheapest baseline on the test years, not merely persistence. Accuracy alone is never reported.',
      ],
    },
    {
      id: 'leakage',
      title: 'Leakage rules',
      table: {
        head: ['', 'Rule'],
        rows: [
          ['R1', 'An input for a given week uses only data dated on or before that week’s map.'],
          ['R2', 'The outcome window starts the week after. No input may look inside it.'],
          ['R3', 'Any “usual” value or percentile is computed from training rows only.'],
          ['R4', 'The 4-week threshold is chosen on validation years. Test years are touched once.'],
          ['R5', 'In forward chaining, a training row’s outcome must end before the test year starts.'],
          ['R6', 'A model trained on shuffled labels must score no better than chance (AUC between 0.40 and 0.60).'],
          ['R7', 'Weeks whose future is not yet known are never trained on or tested on.'],
        ],
      },
      notes: ['Each rule is enforced by an automated test in the pipeline.'],
    },
    {
      id: 'transfer',
      title: 'Transfer test',
      lead: 'Does a model built on one river work on another? The Rio Grande models are applied, unchanged, to four other rivers. A forest retrained on each river’s own counties is the comparison.',
      figure: 'transfer',
      transfer: {
        head: ['River', 'Counties', '', 'Role', 'Severe drought within 4 weeks'],
        // rate: share of county-weeks, 2019 to 2026, followed by severe drought
        // within four weeks. Provisional (Nov 14 runs). Describes the data, not a model.
        rows: [
          ['Rio Grande', 31, 'Focus: all training', '57%'],
          ['Colorado', 13, 'Transfer', '53%'],
          ['Missouri', 103, 'Transfer', '26%'],
          ['Mississippi', 164, 'Transfer', '16%'],
          ['Ohio', 125, 'Transfer', 'about 5%'],
        ],
      },
      notes: [
        'The last column is the share of county-weeks, 2019 to 2026, that were followed by severe drought within four weeks. It is provisional and describes the data, not a model.',
        'It also explains what to expect: the Rio Grande models learn a place where drought is the norm.',
      ],
    },
    {
      id: 'limits',
      title: 'Limits',
      list: [
        'It does not decide, predict or guarantee any USDA payment.',
        'It is not financial or legal advice.',
        'It does not say how to allocate water. Western water rights and interstate compacts decide that.',
        'It does not predict crop yields, and no dollars saved were measured.',
        'It was trained on 31 Rio Grande counties. On other rivers it is a test, not a product.',
        'The Drought Monitor is drawn each week by people. We forecast their map, not the weather itself.',
        'The 31 counties move together, so the evidence is closer to a couple of dozen years than to thousands of rows.',
        'Design choices were made after exploratory runs on the same test years.',
        'River flow, snowpack and weather have not been tested as inputs.',
      ],
    },
  ],
}

// The Solution section is a reserved, empty shell. Add content here later.
export const solution = {
  eyebrow: 'Solution',
  title: 'The solution',
  empty: 'This section is reserved. Its content has not been added yet.',
}

export const closing = {
  title: 'See it for a county.',
  body: 'The outlook itself, with every result and every weak spot, is behind this button.',
}

export const footer = {
  team: '[TEAM NAMES AND SCHOOLS]',
  event: 'Built for the Veritas AI hackathon, AI + Climate track.',
  contact: '[CONTACT EMAIL]',
  credits: [
    { what: 'Drought data', who: 'U.S. Drought Monitor (NDMC, USDA, NOAA); county archive by the Montana Climate Office, CC0', url: 'https://github.com/sustainable-fsa/usdm-counties' },
    { what: 'ENSO index', who: 'NOAA Climate Prediction Center, Oceanic Niño Index', url: 'https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt' },
    { what: 'Map', who: 'Natural Earth rivers; U.S. Census counties and world countries via us-atlas and world-atlas', url: 'https://github.com/nvkelso/natural-earth-vector' },
    { what: 'River reporting', who: 'Cited beside each chapter of the journey', url: '' },
    { what: 'Canyon photograph', who: '[PHOTOGRAPHER AND LICENCE]', url: '' },
    { what: 'Typefaces', who: 'Fraunces; IBM Plex Sans and Mono (SIL Open Font License)', url: '' },
    { what: 'AI tools', who: 'Claude and Claude Code, used to help write this site’s code', url: '' },
  ],
}
