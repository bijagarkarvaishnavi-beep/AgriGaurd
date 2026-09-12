import {useEffect} from 'react';
import {MapContainer,TileLayer,Polygon,Polyline,Marker,useMap,useMapEvents} from 'react-leaflet';
import L from 'leaflet';
import './drawmap.css';

const vertexIcon=L.divIcon({className:'vertex-marker',iconSize:[14,14],iconAnchor:[7,7]});
const round=(v)=>Number(v.toFixed(6));

function ClickCapture({onAdd}){useMapEvents({click:e=>onAdd([round(e.latlng.lat),round(e.latlng.lng)])});return null}

function FitBounds({polygon,fitKey}){
  const map=useMap();
  useEffect(()=>{if(polygon.length>=2)map.fitBounds(L.latLngBounds(polygon),{padding:[24,24],maxZoom:16})},[fitKey]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

export default function FieldDrawMap({polygon,onChange,fitKey}){
  const center=polygon.length?polygon[0]:[51.505,-0.075];
  const move=(i,latlng)=>onChange(polygon.map((p,j)=>j===i?[round(latlng.lat),round(latlng.lng)]:p));
  const remove=(i)=>onChange(polygon.filter((_,j)=>j!==i));
  return <div className="draw-map" data-testid="field-draw-map">
    <div className="draw-toolbar">
      <span>Click map to add a vertex · drag a vertex to move · click a vertex to remove</span>
      <button type="button" data-testid="draw-undo-button" disabled={!polygon.length} onClick={()=>onChange(polygon.slice(0,-1))}>UNDO</button>
      <button type="button" data-testid="draw-clear-button" disabled={!polygon.length} onClick={()=>onChange([])}>CLEAR</button>
    </div>
    <MapContainer center={center} zoom={14} scrollWheelZoom={false} className="draw-canvas">
      <TileLayer attribution="© OpenStreetMap" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"/>
      <ClickCapture onAdd={p=>onChange([...polygon,p])}/>
      <FitBounds polygon={polygon} fitKey={fitKey}/>
      {polygon.length>=3?<Polygon positions={polygon} pathOptions={{color:'#00f0ff',fillColor:'#00f0ff',fillOpacity:.18,weight:2,interactive:false}}/>:polygon.length===2?<Polyline positions={polygon} pathOptions={{color:'#00f0ff',dashArray:'4 6',weight:2,interactive:false}}/>:null}
      {polygon.map((p,i)=><Marker key={`${i}-${p[0]}-${p[1]}`} position={p} draggable icon={vertexIcon} eventHandlers={{dragend:e=>move(i,e.target.getLatLng()),click:()=>remove(i)}}/>)}
    </MapContainer>
    <small className="draw-status" data-testid="draw-vertex-count">{polygon.length} vertices{polygon.length<3?' · add at least 3 to form a field':''}</small>
  </div>;
}
