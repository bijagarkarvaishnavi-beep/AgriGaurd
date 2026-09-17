import {useEffect,useState} from 'react';
import './enhancements.css';
import FieldDrawMap from './FieldDrawMap';

const API=`${process.env.REACT_APP_BACKEND_URL}/api`;
const auth=()=>({Authorization:`Bearer ${localStorage.getItem('token')}`});
async function api(path,opts={}){const r=await fetch(`${API}${path}`,{...opts,headers:{'Content-Type':'application/json',...auth(),...(opts.headers||{})}});if(!r.ok)throw Error((await r.json()).detail||'Request failed');return r.headers.get('content-type')?.includes('pdf')?r.blob():r.json()}
const blank=()=>({
  name:'',
  crop:'Wheat',
  polygon:[],
  text:'[]',
  textError:''
});

function FieldForm({initial,editing,onSaved,onCancel,onError}){
  const [form,setForm]=useState(initial);
  const [fitKey,setFitKey]=useState(0);

  const [selectedLocation,setSelectedLocation]=useState(
    initial.polygon?.length ? initial.polygon[0] : [22.5,79.0]
  );

  const [search,setSearch]=useState('');
  const [locations,setLocations]=useState([]);
  const [locationMessage,setLocationMessage]=useState('');
  const setPolygon=(polygon)=>setForm(f=>({...f,polygon,text:JSON.stringify(polygon),textError:''}));
  async function searchLocation(){
  if(!search.trim()){
    setLocationMessage('Enter a location to search');
    return;
  }

  try{
    setLocationMessage('Searching...');
    setLocations([]);

    const params=new URLSearchParams({
      q:search,
      format:'jsonv2',
      addressdetails:'1',
      countrycodes:'in',
      limit:'5'
    });

    const response=await fetch(
      `https://nominatim.openstreetmap.org/search?${params.toString()}`
    );

    if(!response.ok){
      throw new Error('Search failed');
    }

    const data=await response.json();

    if(!data.length){
      setLocationMessage('Location not found');
      return;
    }

    setLocations(data);
    setLocationMessage('');
  }catch(error){
    setLocationMessage('Could not search location');
  }
}

function useCurrentLocation(){
  if(!navigator.geolocation){
    setLocationMessage('GPS is not supported by this browser');
    return;
  }

  setLocationMessage('Getting current location...');

  navigator.geolocation.getCurrentPosition(
    position=>{
      const lat=Number(position.coords.latitude.toFixed(6));
      const lng=Number(position.coords.longitude.toFixed(6));

      setSelectedLocation([lat,lng]);
      setLocations([]);
      setLocationMessage(`Current location: ${lat}, ${lng}`);
      setFitKey(k=>k+1);
    },
    ()=>{
      setLocationMessage(
        'Could not get location. Allow location permission in browser.'
      );
    },
    {
      enableHighAccuracy:true,
      timeout:10000,
      maximumAge:0
    }
  );
}

function selectLocation(place){
  const lat=Number(place.lat);
  const lng=Number(place.lon);

  setSelectedLocation([lat,lng]);
  setSearch(place.display_name);
  setLocations([]);
  setLocationMessage(`Selected: ${place.display_name}`);
  setFitKey(k=>k+1);
  }
  const onText=(text)=>{try{const p=JSON.parse(text);if(!Array.isArray(p)||p.some(x=>!Array.isArray(x)||x.length!==2||x.some(n=>typeof n!=='number')))throw Error();setForm(f=>({...f,text,polygon:p,textError:''}));setFitKey(k=>k+1)}catch{setForm(f=>({...f,text,textError:'Expected JSON like [[lat,lng],[lat,lng],[lat,lng]]'}))}};
  async function save(e){e.preventDefault();if(form.polygon.length<3)return onError('Draw at least three vertices before saving');try{await api(editing?`/fields/${editing}`:'/fields',{method:editing?'PUT':'POST',body:JSON.stringify({name:form.name,crop:form.crop,polygon:form.polygon})});onSaved()}catch(x){onError(`Could not save field · ${x.message}`)}}
  return <form className="field-form" onSubmit={save} data-testid="field-form">
    <div className="location-selector">

  <h4>📍 FARM LOCATION</h4>

  <p>
    Search country, state, district, village or city,
    or use your current location.
  </p>

  <div className="location-search">

    <input
      value={search}
      onChange={e=>setSearch(e.target.value)}
      placeholder="Search village, district, state or city"
    />

    <button
      type="button"
      onClick={searchLocation}
    >
      🔎 SEARCH
    </button>

    <button
      type="button"
      onClick={useCurrentLocation}
    >
      📍 CURRENT LOCATION
    </button>

  </div>

  {locationMessage && (
    <div className="location-message">
      {locationMessage}
    </div>
  )}

  {locations.length>0 && (
    <div className="location-results">

      {locations.map((place,index)=>(
        <button
          type="button"
          key={`${place.place_id}-${index}`}
          onClick={()=>selectLocation(place)}
        >
          <strong>{place.display_name}</strong>
          <small>{place.type}</small>
        </button>
      ))}

    </div>
  )}

</div>
    <input data-testid="field-name-input" value={form.name} onChange={e=>setForm({...form,name:e.target.value})} placeholder="Field name" required/>
    <input data-testid="field-crop-input" value={form.crop} onChange={e=>setForm({...form,crop:e.target.value})} placeholder="Crop" required/>
   <FieldDrawMap
  polygon={form.polygon}
  onChange={setPolygon}
  fitKey={fitKey}
  selectedLocation={selectedLocation}
  />
    <textarea data-testid="field-polygon-input" value={form.text} onChange={e=>onText(e.target.value)} aria-label="Field polygon coordinates as [lat,lng] pairs"/>
    {form.textError&&<div className="text-error" data-testid="field-polygon-error">{form.textError}</div>}
    <div><button data-testid="save-field-button">SAVE FIELD</button><button type="button" data-testid="cancel-field-button" onClick={onCancel}>CANCEL</button></div>
  </form>;
}

function HistoryChart({history}){
  if(!history.length)return <p className="muted">Run a SAR analysis to populate field history.</p>;
  return <div className="history-chart" data-testid="flood-history-chart">{history.slice(0,8).reverse().map((h,i)=><div className="bar-column" key={h.id||i}><div className={`bar sev-${h.severity?.toLowerCase()}`} style={{height:`${Math.max(10,h.flood_percentage)}%`}}><span>{h.flood_percentage}%</span></div><small>{h.after_date}</small></div>)}</div>;
}

function SavedReports({fieldId,refreshKey}){
  const [reports,setReports]=useState([]);
  useEffect(()=>{if(fieldId)api(`/fields/${fieldId}/reports`).then(setReports).catch(()=>setReports([]));else setReports([])},[fieldId,refreshKey]);
  async function download(r){const blob=await api(`/reports/${r.id}`);const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=r.filename;a.click();URL.revokeObjectURL(url)}
  if(!reports.length)return null;
  return <div className="saved-reports" data-testid="saved-reports"><b>SAVED REPORTS · PERSISTENT</b>{reports.slice(0,5).map(r=><button type="button" key={r.id} data-testid={`saved-report-${r.id}`} onClick={()=>download(r)}><span>{r.created_at.slice(0,16).replace('T',' ')}</span><span>{r.flood_percentage}% · {r.severity}</span><span>⇩ {(r.size_bytes/1024).toFixed(0)} KB</span></button>)}</div>;
}

export default function Enhancements(){
  const [fields,setFields]=useState([]);const [history,setHistory]=useState([]);const [editing,setEditing]=useState(null);const [showForm,setShowForm]=useState(false);const [initial,setInitial]=useState(blank());const [message,setMessage]=useState('');const [storage,setStorage]=useState('');const [reportKey,setReportKey]=useState(0);
  const load=()=>api('/fields').then(setFields).catch(()=>{});
  useEffect(()=>{load();fetch(`${API}/`).then(r=>r.json()).then(d=>setStorage(d.storage)).catch(()=>{});const onOpen=()=>{open();document.querySelector('[data-testid="farmer-tools-section"]')?.scrollIntoView({behavior:'smooth'})};window.addEventListener('open-new-field',onOpen);window.addEventListener('fields-changed',load);return()=>{window.removeEventListener('open-new-field',onOpen);window.removeEventListener('fields-changed',load)}},[]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(()=>{if(fields[0])api(`/fields/${fields[0].id}/analyses`).then(setHistory).catch(()=>{});else setHistory([])},[fields]);
  function open(field){setEditing(field?.id||null);setInitial(field?{name:field.name,crop:field.crop,polygon:field.polygon,text:JSON.stringify(field.polygon),textError:''}:blank());setShowForm(true)}
  async function remove(id){if(!window.confirm('Delete this field and its saved analyses?'))return;try{await api(`/fields/${id}`,{method:'DELETE'});setMessage('Field deleted');load();window.dispatchEvent(new Event('fields-changed'))}catch(x){setMessage(`Could not delete · ${x.message}`)}}
  async function report(){if(!fields[0])return;try{const blob=await api(`/fields/${fields[0].id}/report`);const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`${fields[0].name.replaceAll(' ','_')}_flood_report.pdf`;a.click();URL.revokeObjectURL(url);setReportKey(k=>k+1);setMessage('Flood evidence PDF downloaded · saved to persistent reports')}catch(x){setMessage(`Report failed · ${x.message}`)}}
  return <section className="enhancements" data-testid="farmer-tools-section">
    <div className="tools-head"><div><span className="eyebrow">FIELD WORKBENCH</span><h3>Farmer field tools</h3><p>Draw boundaries on the map · exact geodesic area · <b data-testid="storage-mode">{storage||'…'}</b></p></div>
      <div className="tool-actions"><button data-testid="new-field-button" onClick={()=>open()}>＋ NEW FIELD</button><button data-testid="download-report-button" onClick={report}>⇩ FLOOD REPORT</button></div></div>
    <div className="tools-grid">
      <section className="tool-panel"><div className="panel-title"><b>FIELD EDITOR</b><span className="demo">DRAW · EDIT · DELETE</span></div>
        {fields.map(f=><div className="field-row" data-testid={`field-row-${f.id}`} key={f.id}><div><strong>{f.name}</strong><small>{f.crop} · {f.hectares} ha · {f.acres} ac · {f.polygon.length} vertices</small></div><button data-testid={`edit-field-${f.id}`} onClick={()=>open(f)}>EDIT</button><button data-testid={`delete-field-${f.id}`} className="danger" onClick={()=>remove(f.id)}>DELETE</button></div>)}
        {showForm&&<FieldForm key={editing||'new'} initial={initial} editing={editing} onCancel={()=>{setEditing(null);setShowForm(false)}} onError={setMessage} onSaved={()=>{setMessage(editing?'Field boundary updated · area recalculated':'Field saved with exact geodesic area');setEditing(null);setShowForm(false);load();window.dispatchEvent(new Event('fields-changed'))}}/>}
      </section>
      <section className="tool-panel"><div className="panel-title"><b>FLOOD HISTORY</b><span className="demo">SAVED ANALYSES</span></div><HistoryChart history={history}/><SavedReports fieldId={fields[0]?.id} refreshKey={reportKey}/><div className="report-note">Insurance-supporting evidence only · NOT an official insurance assessment</div></section>
    </div>
    {message&&<div className="tool-message" data-testid="tools-message">{message}</div>}
  </section>;
}
