import { useState, useEffect } from 'react'
import axios from 'axios'
import './App.css' // Moveremos el CSS global aquí

const API_URL = 'http://107.23.142.61:8000/api'
const USER_ID = 1
const CP_ID = 1

function App() {
  const [charging, setCharging] = useState(false)
  const [status, setStatus] = useState('Listo para cargar')
  const [power, setPower] = useState('—')
  const [energy, setEnergy] = useState(0.0)
  const [duration, setDuration] = useState(0)
  const [meterWidth, setMeterWidth] = useState(67)
  const [range, setRange] = useState(284)
  const [timer, setTimer] = useState(null)

  const handleChargeToggle = async () => {
    if (!charging) {
      try {
        setStatus('Autorizando hardware...')
        
        // 1. Candado Digital
        const start = new Date()
        const end = new Date(start.getTime() + 60*60*1000)
        await axios.post(`${API_URL}/reservar`, {
          user_id: USER_ID, charge_point_id: CP_ID, 
          start_time: start.toISOString(), end_time: end.toISOString()
        })

        // 2. Encendido
        await axios.post(`${API_URL}/iniciar_carga`, { user_id: USER_ID, charge_point_id: CP_ID })
        
        setCharging(true)
        setStatus('Cargando tu vehículo')
        setPower('7.2')
        
        // Simulador de Front (Se reemplazará con polling al GET /sesion/activa)
        let mins = 0
        let kwh = 0
        const interval = setInterval(() => {
          mins++
          kwh += 0.12
          setEnergy(kwh.toFixed(1))
          setDuration(mins)
          setMeterWidth(Math.min(67 + mins * 0.28, 100))
          setRange(284 + Math.round(kwh * 5.8))
        }, 5000)
        setTimer(interval)
        
      } catch (e) {
        setStatus('Error de conexión')
      }
    } else {
      try {
        setStatus('Deteniendo hardware...')
        await axios.post(`${API_URL}/detener_carga`, { user_id: USER_ID, charge_point_id: CP_ID })
        
        clearInterval(timer)
        setCharging(false)
        setStatus('Carga finalizada')
        setPower('—')
      } catch (e) {
        setStatus('Error al detener')
      }
    }
  }

  return (
    <main className="phone" aria-label="Aplicación Cynergiax">
      <section className="home">
        <header className="greeting">
          <div>
            <p className="eyebrow">MIÉRCOLES, 3 SEP</p>
            <h1>Hola, Andrés</h1>
          </div>
          <div className="avatar">AM</div>
        </header>

        <div className="connected">
          <span className="dot"></span> CARGADOR CONECTADO
        </div>

        <article className="charge-card">
          <p className="charger-name">VOLTA HOME · VC-0428</p>
          <h2 className="state">{status}</h2>
          
          <div className="metrics">
            <div className="metric">
              <strong>{power}</strong><span>POTENCIA</span>
            </div>
            <div className="metric">
              <strong>{energy}</strong><span>kWh HOY</span>
            </div>
            <div className="metric">
              <strong>{duration}m</strong><span>SESIÓN</span>
            </div>
          </div>
          
          <div className="meter"><i style={{ width: `${meterWidth}%` }}></i></div>
          <div className="subline">
            <span>Autonomía estimada</span><span>{range} km</span>
          </div>
          
          <button 
            onClick={handleChargeToggle} 
            className={`primary ${charging ? 'stop' : ''}`}>
            {charging ? 'Terminar carga' : 'Iniciar carga'}
          </button>
        </article>

        <div className="section"><h2>Acciones rápidas</h2></div>
        <div className="quick">
          <button className="tile">
            <div className="tile-icon">qr</div>
            <strong>Escanear QR</strong><span>Conecta otro cargador</span>
          </button>
          <button className="tile">
            <div className="tile-icon">⌁</div>
            <strong>Mi consumo</strong><span>Uso y costos del mes</span>
          </button>
        </div>
      </section>
    </main>
  )
}

export default App