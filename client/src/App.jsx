import React, { useState } from "react";
import { Info } from "lucide-react";

export default function App() {
  const [input, setInput] = useState(""); // username or fanpage URL
  const [loading, setLoading] = useState(false);
  const [recs, setRecs] = useState([]);
  const [error, setError] = useState("");

  // Set in Vercel: VITE_API_URL=https://your-backend.onrender.com
  const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:5000";

  const go = async () => {
    setLoading(true); setError(""); setRecs([]);
    try {
      const res = await fetch(`${API_BASE}/recommend`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Request failed");
      setRecs(data.recommendations || []);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <div style={{minHeight:"100vh", background:"#fafafa", color:"#111"}}>
      <header style={{maxWidth:800, margin:"0 auto", padding:"32px 16px"}}>
        <h1 style={{fontSize:28, fontWeight:800}}>🎚️ Cratebuddy</h1>
        <p style={{opacity:.7}}>Bandcamp-powered crate digging: paste a fan page URL or username and get similar tracks.</p>
        <div style={{marginTop:12, display:"flex", gap:8}}>
          <input
            style={{flex:1, border:"1px solid #ddd", borderRadius:12, padding:"10px 12px"}}
            placeholder="e.g. https://bandcamp.com/yourname or just yourname"
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          <button onClick={go} disabled={!input || loading}
            style={{borderRadius:12, background:"black", color:"white", padding:"10px 14px", opacity:(!input||loading)?0.6:1}}>
            {loading ? "Digging…" : "Get Recs"}
          </button>
        </div>
        {error && <p style={{color:"#d00", marginTop:8}}>{error}</p>}
      </header>

      <main style={{maxWidth:1000, margin:"0 auto", padding:"0 16px 80px"}}>
        <ul style={{display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(320px, 1fr))", gap:16}}>
          {recs.map((r, i) => (
            <li key={i} className="card" style={{position:"relative"}}>
              <a href={r.url} target="_blank" rel="noreferrer" style={{display:"block", padding:16, border:"1px solid #e5e5e5", borderRadius:16, background:"white"}}>
                <div style={{display:"flex", justifyContent:"space-between", gap:12}}>
                  <div>
                    <h3 style={{margin:"0 0 2px", fontWeight:600}}>{r.title}</h3>
                    <p style={{margin:0, fontSize:14, opacity:.7}}>{r.artist}</p>
                    {r.label && <p style={{margin:"6px 0 0", fontSize:12, opacity:.6}}>Label: {r.label}</p>}
                    {Array.isArray(r.tags) && r.tags.length>0 && (
                      <p style={{margin:"6px 0 0", fontSize:12, opacity:.6}}>Tags: {r.tags.slice(0,6).join(", ")}{r.tags.length>6?"…":""}</p>
                    )}
                  </div>
                  <div style={{textAlign:"right"}}>
                    <div style={{fontSize:20, fontWeight:800, fontVariantNumeric:"tabular-nums"}}>{r.total_score?.toFixed?.(2)}</div>
                    <div style={{fontSize:10, textTransform:"uppercase", opacity:.6}}>score</div>
                  </div>
                </div>
              </a>

              {/* Info popover */}
              <div style={{position:"absolute", top:10, right:10}}>
                <div className="info" style={{position:"relative"}}>
                  <span title="Why this rec" style={{display:"inline-flex", alignItems:"center", justifyContent:"center", width:24, height:24, borderRadius:999, background:"#111", color:"#fff"}}>
                    <Info size={14} />
                  </span>
                  <div className="popover" style={{position:"absolute", right:0, marginTop:8, width:300, border:"1px solid #e5e5e5", borderRadius:12, background:"white", padding:12, boxShadow:"0 6px 24px rgba(0,0,0,.06)", display:"none"}}>
                    <p style={{fontSize:12, fontWeight:700, margin:"0 0 6px"}}>Why this rec</p>
                    <div style={{fontSize:12, display:"grid", gap:4}}>
                      <div style={{display:"flex", justifyContent:"space-between"}}><span>Co‑purchase</span><span style={{fontVariantNumeric:"tabular-nums"}}>{(r.breakdown?.copurchase ?? 0).toFixed(3)}</span></div>
                      <div style={{display:"flex", justifyContent:"space-between"}}><span>Label/Artist</span><span style={{fontVariantNumeric:"tabular-nums"}}>{(r.breakdown?.label_artist ?? 0).toFixed(3)}</span></div>
                      <div style={{display:"flex", justifyContent:"space-between"}}><span>Genre/Tags</span><span style={{fontVariantNumeric:"tabular-nums"}}>{(r.breakdown?.tags ?? 0).toFixed(3)}</span></div>
                      <hr style={{margin:"6px 0"}} />
                      <div style={{display:"flex", justifyContent:"space-between", fontWeight:700}}><span>Total</span><span style={{fontVariantNumeric:"tabular-nums"}}>{(r.total_score ?? 0).toFixed(3)}</span></div>
                      <p style={{margin:"6px 0 0", fontSize:10, opacity:.6}}>Weights — co: {WEIGHTS.copurchase}, la: {WEIGHTS.label_artist}, tags: {WEIGHTS.tags}</p>
                    </div>
                  </div>
                </div>
              </div>
              <style>{`
                .card:hover .popover { display: block; }
              `}</style>
            </li>
          ))}
        </ul>
      </main>
    </div>
  );
}

// Display-only (backend is source of truth)
export const WEIGHTS = { copurchase: 0.6, label_artist: 0.3, tags: 0.1 };