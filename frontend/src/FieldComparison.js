import {useEffect,useState} from 'react';
import {MapContainer,TileLayer,Polygon,Tooltip,useMap} from 'react-leaflet';
import L from 'leaflet';
import './comparison.css';

const API=`${process.env.REACT_APP_BACKEND_URL}/api`;
const COLORS={HIGH:'#ff5b53',MEDIUM:'#f2b035',LOW:'#26d69a',NONE:'#6b7a86'};
const sevOf=(f)=>f.latest_analysis?.severity||'NONE';

function Focus({fields,focus}){
  const map=useMap();
  useEffect(()=>{
    const target=focus?fields.filter(f=>f.id===focus):fields;
    const pts=target.flatMap(f=>f.polygon);
    if(pts.length)map.fitBounds(L.latLngBounds(pts),{padding:[30,30],maxZoom:focus?16:14});
  },[fields,focus]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

export default function FieldComparison(){
  const [fields,setFields]=useState([]);const [focus,setFocus]=useState(null);const [error,setError]=useState('');
  const load=()=>fetch(`${API}/fields/overview`,{headers:{Authorization:`Bearer ${localStorage.getItem('token')}`}}).then(r=>{if(!r.ok)throw Error('Could not load field overview');return r.json()}).then(setFields).catch(e=>setError(e.message));
  useEffect(()=>{load();window.addEventListener('fields-changed',load);return()=>window.removeEventListener('fields-changed',load)},[]);
  if(!fields.length)return null;
  const counts=fields.reduce((a,f)=>({...a,[sevOf(f)]:(a[sevOf(f)]||0)+1}),{});
  return <section className="comparison" data-testid="field-comparison-section">
    <div className="comparison-head"><div><span className="eyebrow">ALL FIELDS · {fields.length}</span><h3>Field comparison</h3><p>Every boundary you own, coloured by the latest saved flood severity.</p></div>
      <div className="sev-legend" data-testid="comparison-legend">{Object.entries(COLORS).map(([k,c])=><span key={k}><i style={{background:c}}/>{k==='NONE'?'NO ANALYSIS':k} <b>{counts[k]||0}</b></span>)}</div></div>
    {error&&<div className="notice" data-testid="comparison-error">{error}</div>}
    <div className="comparison-grid">
      <div className="comparison-map" data-testid="comparison-map"><MapContainer center={fields[0].polygon[0]} zoom={13} scrollWheelZoom={false}><TileLayer attribution="© OpenStreetMap" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"/><Focus fields={fields} focus={focus}/>
        {fields.map(f=><Polygon key={f.id} positions={f.polygon} pathOptions={{color:COLORS[sevOf(f)],fillColor:COLORS[sevOf(f)],fillOpacity:focus&&focus!==f.id?.12:.4,weight:focus===f.id?4:2}} eventHandlers={{click:()=>setFocus(f.id)}}><Tooltip sticky>{f.name} · {f.latest_analysis?`${f.latest_analysis.flood_percentage}% flooded`:'no analysis yet'}</Tooltip></Polygon>)}
      </MapContainer></div>
      <div className="comparison-list">
        <button type="button" className={`cmp-row all ${focus?'':'on'}`} data-testid="comparison-show-all" onClick={()=>setFocus(null)}>SHOW ALL FIELDS</button>
        {fields.map(f=><button type="button" key={f.id} data-testid={`comparison-field-${f.id}`} className={`cmp-row ${focus===f.id?'on':''}`} onClick={()=>setFocus(focus===f.id?null:f.id)}>
          <i style={{background:COLORS[sevOf(f)]}}/><div><strong>{f.name}</strong><small>{f.crop} · {f.hectares} ha</small></div>
          <em data-testid={`comparison-pct-${f.id}`}>{f.latest_analysis?<>{f.latest_analysis.flood_percentage}%<small>{f.latest_analysis.severity}</small></>:<small>NO SCAN</small>}</em>
        </button>)}
      </div>
    </div>
  </section>;
}
