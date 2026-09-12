import {useEffect,useState} from 'react'; import './trend.css';
const API=`${process.env.REACT_APP_BACKEND_URL}/api`;
export default function TrendSignals(){
  const [history,setHistory]=useState([]);
  useEffect(()=>{
    const load=async()=>{try{const headers={Authorization:`Bearer ${localStorage.getItem('token')}`};const fields=await (await fetch(`${API}/fields`,{headers})).json();if(!Array.isArray(fields)||!fields[0])return setHistory([]);const h=await (await fetch(`${API}/fields/${fields[0].id}/analyses`,{headers})).json();setHistory(Array.isArray(h)?h:[])}catch{setHistory([])}};
    load();window.addEventListener('fields-changed',load);return()=>window.removeEventListener('fields-changed',load);
  },[]);
  const latest=history[0],previous=history[1];
  const delta=latest&&previous?Number((latest.flood_percentage-previous.flood_percentage).toFixed(1)):0;
  return <section className="trend-signals" data-testid="trend-signals-section"><span className="eyebrow">TREND SIGNAL</span><strong className={delta>0?'trend-up':delta<0?'trend-down':'trend-flat'}>{delta>0?'↑':delta<0?'↓':'→'} {Math.abs(delta)}%</strong><small>{latest&&previous?'flood extent change vs previous scan':latest?'Awaiting a second scan for change detection':'No saved scans yet'}</small></section>;
}
