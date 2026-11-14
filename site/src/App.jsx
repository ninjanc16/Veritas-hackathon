import Closing from './components/Closing.jsx'
import Journey from './components/journey/Journey.jsx'
import Paper from './components/paper/Paper.jsx'
import Solution from './components/Solution.jsx'
import TopBar from './components/TopBar.jsx'

// The page in one read: a scroll journey down the river (the problem and the
// idea), the method set as a paper, a reserved Solution section, and the way
// into the tool.
export default function App() {
  return (
    <>
      <a href="#method" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:bg-amber focus:px-4 focus:py-2 focus:text-umber-950">
        Skip to the method
      </a>
      <TopBar />
      <main>
        <Journey />
        <Paper />
        <Solution />
      </main>
      <Closing />
    </>
  )
}
