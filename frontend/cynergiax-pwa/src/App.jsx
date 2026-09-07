import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

const API_URL = `${import.meta.env.VITE_API_URL || 'http://apicargadores.cynergiax.com:8000'}/api`;
const USER_ID = 1;
const CP_ID = 1;

export default function App() {
  const [activePage, setActivePage] = useState('home');
  const [charging, setCharging] = useState(false);
  const [statusText, setStatusText] = useState('Listo para cargar');
  const [power, setPower] = useState('—');
  const [energy, setEnergy] = useState('0.0');
  const [duration, setDuration] = useState('0m');
  const [sessionCost, setSessionCost] = useState('$ 0');
  const [range, setRange] = useState('284 km');
  const [meterWidth, setMeterWidth] = useState(0);
  const [ratePerKwh, setRatePerKwh] = useState(1850);
  const [chargerName, setChargerName] = useState('VC-0428');
  const [locationName, setLocationName] = useState('COMUNIDAD VOLTA NORTE');

  // Estados de Usuario e Historial
  const [userData, setUserData] = useState({ nombre: 'Volta Blue', avatar: 'VB' });
  const [historyStats, setHistoryStats] = useState({ total_sesiones: 0, total_kwh: 0, costo_total_cop: 0 });
  
  // Modales
  const [scannerOpen, setScannerOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmConfig, setConfirmConfig] = useState({ title: '', text: '', action: null, label: 'Confirmar' });
  
  // Escáner QR
  const [scanState, setScanState] = useState({ text: 'BUSCANDO CÓDIGO…', resultShow: false, btnText: 'Simular escaneo' });
  const [manualEntryShow, setManualEntryShow] = useState(false);
  const [manualCode, setManualCode] = useState('');

  // Generación Dinámica de los próximos 7 días a partir de hoy
  const daysList = React.useMemo(() => {
    const list = [];
    const baseDate = new Date(); 
    const optionsWeekday = { weekday: 'short' };
    const optionsMonth = { day: 'numeric', month: 'short' };

    for (let i = 0; i < 7; i++) {
      const d = new Date(baseDate);
      d.setDate(baseDate.getDate() + i);
      const dateVal = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      const label = i === 0 ? 'Hoy' : d.toLocaleDateString('es-ES', optionsWeekday);
      const text = d.toLocaleDateString('es-ES', optionsMonth);
      list.push({ label: label.charAt(0).toUpperCase() + label.slice(1), dateVal, text });
    }
    return list;
  }, []);

  // Reservas Dinámicas con Hora y Minuto
  const [selectedDay, setSelectedDay] = useState(daysList[0]);
  const [startHour, setStartHour] = useState('22');
  const [startMinute, setStartMinute] = useState('00');
  const [totalHours, setTotalHours] = useState(2);
  const [reservationConfirmed, setReservationConfirmed] = useState(false);
  const [reservationId, setReservationId] = useState(null); 
  const [reservationData, setReservationData] = useState({ time: 'Sin reserva activa', status: 'Completada' });
  const [hasReservation, setHasReservation] = useState(false);
  
  const copFormatter = new Intl.NumberFormat('es-CO');

  useEffect(() => {
    fetchUserData();
    fetchHistoryData();
    fetchLocationData();
    checkActiveSession();

    const interval = setInterval(() => {
      checkActiveSession();
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  const availableHoursList = React.useMemo(() => {
    const allHours = Array.from({length: 24}, (_, i) => String(i).padStart(2, '0'));
    const todayStr = `${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, '0')}-${String(new Date().getDate()).padStart(2, '0')}`;
    
    if (selectedDay.dateVal === todayStr) {
      const now = new Date();
      const currentHour = now.getHours(); 
      const currentMinute = now.getMinutes();
      const minHour = currentMinute >= 45 ? currentHour + 1 : currentHour;
      return allHours.filter(h => parseInt(h, 10) >= minHour);
    }
    return allHours;
  }, [selectedDay]);

  const availableMinutesList = React.useMemo(() => {
    const allMinutes = ['00', '15', '30', '45'];
    const todayStr = `${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, '0')}-${String(new Date().getDate()).padStart(2, '0')}`;
    
    if (selectedDay.dateVal === todayStr) {
      const now = new Date();
      const currentHourStr = String(now.getHours()).padStart(2, '0');
      const currentMinute = now.getMinutes();
      
      // Asegurarse de que permita los minutos actuales (>= en lugar de >)
      if (startHour === currentHourStr) {
        return allMinutes.filter(m => parseInt(m, 10) >= currentMinute);
      }
    }
    return allMinutes;
  }, [selectedDay, startHour]);

  useEffect(() => {
    if (availableHoursList.length > 0 && !availableHoursList.includes(startHour)) {
      setStartHour(availableHoursList[0]);
    }
  }, [availableHoursList, startHour]);

  useEffect(() => {
    if (availableMinutesList.length > 0 && !availableMinutesList.includes(startMinute)) {
      setStartMinute(availableMinutesList[0]);
    }
  }, [availableMinutesList, startMinute]);

  const fetchLocationData = async () => {
    try {
      const res = await axios.get(`${API_URL}/ubicacion/${CP_ID}`);
      if (res.data && res.data.nombre) {
        setLocationName(res.data.nombre.toUpperCase());
      }
    } catch (e) {
      console.error('Error al sincronizar ubicación');
    }
  };

  const fetchUserData = async () => {
    try {
      const res = await axios.get(`${API_URL}/usuario/${USER_ID}`);
      if(res.data.nombre) setUserData(res.data);
    } catch (e) {
      console.error('Error al sincronizar usuario');
    }
  };

  const fetchHistoryData = async () => {
    try {
      const res = await axios.get(`${API_URL}/usuario/${USER_ID}/historial`);
      setHistoryStats(res.data);
    } catch (e) {
      console.error('Error al sincronizar historial');
    }
  };

  const checkActiveSession = async () => {
    try {
      const res = await axios.get(`${API_URL}/sesion/activa/${USER_ID}`);
      
      if (res.data.precio_por_kwh) setRatePerKwh(res.data.precio_por_kwh);
      if (res.data.ocpp_id) setChargerName(res.data.ocpp_id);

      if (reservationData.status === 'Reservado' || res.data.activa) {
        setHasReservation(true);
      } else {
        setHasReservation(false);
      }

      if (res.data.activa) {
        setCharging(true);
        setStatusText('Cargando tu vehículo');
        setPower(`${res.data.potencia_kw} kW`);
        setEnergy(res.data.energia_kwh.toFixed(1));
        setDuration(`${res.data.minutos}m`);
        setSessionCost(`$ ${copFormatter.format(Math.round(res.data.costo_estimado))}`);
        setMeterWidth(Math.min(67 + (res.data.minutos * 0.8), 100));
      } else {
        setCharging(false);
        if (!hasReservation && reservationData.status !== 'Reservado') {
          setStatusText('Requiere reserva previa');
        } else {
          setStatusText('Listo para cargar');
        }
        setPower('—');
        setEnergy('0.0');
        setDuration('0m');
        setSessionCost('$ 0');
        setMeterWidth(0);
      }
    } catch (e) {
      console.error('Error al verificar sesión activa');
    }
  };

  const handleChargeToggle = async () => {
    if (!charging) {
      try {
        setStatusText('Autorizando con backend...');
        await axios.post(`${API_URL}/iniciar_carga`, {
          user_id: USER_ID,
          charge_point_id: CP_ID
        });
        
        setCharging(true);
        setStatusText('Cargando tu vehículo');
        setPower('7.2');
        setMeterWidth(67);
      } catch (error) {
        const errorMsg = error.response?.data?.detail || 'Error al conectar con el cargador';
        setStatusText('Listo para cargar');
        alert('Fallo al iniciar carga: ' + errorMsg);
      }
    } else {
      askConfirmation(
        '¿Terminar esta carga?',
        'Se detendrá el suministro y se liberará el tiempo restante.',
        async () => {
          try {
            await axios.post(`${API_URL}/detener_carga`, {
              user_id: USER_ID,
              charge_point_id: CP_ID
            });
            setCharging(false);
            setStatusText('Listo para cargar');
            setPower('—');
            setMeterWidth(0);
            
            // LIMPIEZA TOTAL DEL ESTADO DE RESERVA
            setHasReservation(false);
            setReservationData({ time: 'Sin reserva activa', status: 'Completada' });
            
            fetchHistoryData();
          } catch (error) {
            alert('Error al detener la carga');
          }
        },
        'Terminar carga'
      );
    }
  };

  const askConfirmation = (title, text, action, label = 'Confirmar') => {
    setConfirmConfig({ title, text, action, label });
    setConfirmOpen(true);
  };

  const getEndTime = () => {
    if (!startHour || !startMinute) return '';
    const h = parseInt(startHour, 10);
    const endH = (h + totalHours) % 24;
    return `${String(endH).padStart(2, '0')}:${startMinute}`;
  };

  const handleConfirmReservation = async () => {
    try {
      const startTimeISO = `${selectedDay.dateVal} ${startHour}:${startMinute}:00`;
      const endTimeISO = `${selectedDay.dateVal} ${getEndTime()}:00`; 

      const res = await axios.post(`${API_URL}/reservar`, {
        user_id: USER_ID,
        charge_point_id: CP_ID,
        start_time: startTimeISO,
        end_time: endTimeISO
      });

      if (res.data.id_reserva) {
        setReservationId(res.data.id_reserva);
      }

      const finalTimeStr = `${selectedDay.label} · ${startHour}:${startMinute} — ${getEndTime()}`;
      setReservationData({ time: finalTimeStr, status: 'Reservado' });
      setHasReservation(true);
      setReservationConfirmed(true);
      setTimeout(() => { setActivePage('reservations'); setReservationConfirmed(false); }, 1200);
    } catch (error) {
      const errMsg = error.response?.data?.detail || 'Conflicto: El cargador ya está reservado en esta franja horaria.';
      alert(errMsg);
    }
  };

  const handleCancelReservation = () => {
    askConfirmation(
      '¿Cancelar esta reserva?',
      'La franja volverá a estar disponible para otros residentes.',
      async () => {
        try {
          if (reservationId) {
            await axios.post(`${API_URL}/reservar/cancelar`, { reservation_id: reservationId });
          }
          setReservationData({ time: 'Sin reserva activa', status: 'Cancelada' });
          setHasReservation(false);
        } catch (error) {
          alert('Error al cancelar la reserva en el servidor');
        }
      },
      'Cancelar reserva'
    );
  };

  // Función de apoyo para colorear los estados de la reserva
  const getStatusColor = (status) => {
    if (status === 'Cancelada') return { color: '#fca5a5', bg: 'rgba(248,113,113,.13)' };
    if (status === 'Completada') return { color: '#94a3b8', bg: 'rgba(148,163,184,.13)' };
    return { color: '#bbf7d0', bg: 'rgba(34,197,94,.12)' }; // Default (Reservado/Activa)
  };

  return (
    <main className="phone" aria-label="Aplicación Volta">
      
      {/* VISTA: INICIO */}
      <section className={`home ${activePage !== 'home' ? 'hide' : ''}`} id="home">
        <div className="top">
          <span>9:41</span>
          <div className="status"><span>5G</span><span className="signal"><i></i><i></i><i></i><i></i></span><span>●</span></div>
        </div>
        <header className="greeting">
          <div><p className="eyebrow">DOMINGO, 6 SEP</p><h1>Hola, {userData.nombre}</h1></div>
          <div className="avatar" aria-label={`Perfil de ${userData.nombre}`}>{userData.avatar}</div>
        </header>
        <div className="connected"><span className="dot"></span> CARGADOR CONECTADO</div>
        
        <article className="charge-card">
          <p className="charger-name">{locationName} · {chargerName}</p>
          <h2 className="state" aria-live="polite">{statusText}</h2>
          <div className="metrics">
            <div className="metric"><strong aria-live="polite">{energy}</strong><span>kWh HOY</span></div>
            <div className="metric cost"><strong aria-live="polite">{sessionCost}</strong><span>COSTO ESTIMADO · COP</span></div>
            <div className="metric"><strong aria-live="polite">{power}</strong><span>POTENCIA</span></div>
            <div className="metric"><strong aria-live="polite">{duration}</strong><span>SESIÓN</span></div>
          </div>
          <div className="meter"><i style={{ width: `${meterWidth}%` }}></i></div>
          <div className="subline"><span>Autonomía estimada</span><span aria-live="polite">{range}</span></div>
          <p className="rate-note">Tarifa vigente: {copFormatter.format(ratePerKwh)} COP/kWh (BD). No incluye cargos adicionales.</p>
          <button 
            onClick={handleChargeToggle} 
            disabled={!charging && !hasReservation}
            className={`primary ${charging ? 'stop' : ''}`}
            style={{ opacity: (!charging && !hasReservation) ? 0.4 : 1, cursor: (!charging && !hasReservation) ? 'not-allowed' : 'pointer' }}
          >
            {charging ? 'Terminar carga' : (hasReservation ? 'Iniciar carga' : 'Requiere reserva')}
          </button>
        </article>

        <div className="section"><h2>Acciones rápidas</h2></div>
        <div className="quick">
          <button className="tile booking-tile" onClick={() => setActivePage('booking')}>
            <div className="tile-icon">◷</div>
            <div><strong>Agendar una carga</strong><span>Reserva una franja en tu comunidad</span></div>
            <div className="tile-arrow">›</div>
          </button>
          <button className="tile" onClick={() => setScannerOpen(true)}>
            <div className="tile-icon"><span className="qr-mark" aria-hidden="true"></span></div>
            <strong>Escanear QR</strong><span>Conecta otro cargador</span>
          </button>
          <button className="tile" onClick={() => setActivePage('usage')}>
            <div className="tile-icon">⌁</div>
            <strong>Mi consumo</strong><span>Uso y costos de este mes</span>
          </button>
        </div>

        <div className="section"><h2>Tus reservas</h2><button className="link" onClick={() => setActivePage('reservations')}>Ver todas</button></div>
        <button className="activity" onClick={() => setActivePage('reservations')} style={{ width: '100%', textAlign: 'left', color: 'inherit', fontFamily: 'inherit', cursor: 'pointer' }}>
          <div className="activity-icon">◷</div>
          <div><h3 id="homeReservationCharger">Cargador {chargerName}</h3><p id="homeReservationTime">{reservationData.time}</p></div>
          <b style={{ color: getStatusColor(reservationData.status).color }}>{reservationData.status}</b>
        </button>

        <div className="section"><h2>Última sesión</h2><button className="link" onClick={() => setActivePage('history')}>Ver historial</button></div>
        <div className="activity">
          <div className="activity-icon">ϟ</div>
          <div><h3>{locationName} · {chargerName}</h3><p>Ayer · 20:14 — 22:03</p></div>
          <b>16.8 kWh</b>
        </div>
      </section>

      {/* VISTA: CONSUMO CON DATOS DE BD */}
      <section className={`detail-page ${activePage === 'usage' ? 'show' : ''}`} id="usage">
        <button className="back" onClick={() => setActivePage('home')}>← Inicio</button>
        <p className="eyebrow" style={{ marginTop: '28px' }}>SEPTIEMBRE 2026</p>
        <h1 style={{ fontSize: '28px', margin: '4px 0' }}>Tu energía</h1>
        <div className="big-total">{historyStats.total_kwh} <small style={{ fontSize: '17px', color: 'var(--muted)' }}>kWh</small></div>
        <p className="amount"><span id="monthlyCost">$ {copFormatter.format(historyStats.costo_total_cop)} COP</span> · {historyStats.total_sesiones} sesiones registradas</p>
        <p className="rate-note">Cálculo basado en tarifas actuales ({copFormatter.format(ratePerKwh)} COP/kWh).</p>
        <div className="chart" style={{ marginTop: '20px' }}>
          <div className="bar" data-day="L" style={{ height: '36%' }}></div>
          <div className="bar" data-day="M" style={{ height: '54%' }}></div>
          <div className="bar" data-day="X" style={{ height: '28%' }}></div>
          <div className="bar" data-day="J" style={{ height: '77%' }}></div>
          <div className="bar" data-day="V" style={{ height: '48%' }}></div>
          <div className="bar" data-day="S" style={{ height: '88%' }}></div>
          <div className="bar" data-day="D" style={{ height: '61%' }}></div>
        </div>
        <div className="section"><h2>Datos de uso</h2></div>
        <div className="quick">
          <div className="tile"><strong id="costTotal">$ {copFormatter.format(historyStats.costo_total_cop)}</strong><span>Costo total</span></div>
          <div className="tile"><strong>{historyStats.total_sesiones}</strong><span>Sesiones totales</span></div>
          <div className="tile"><strong>4.2 kg</strong><span>CO₂ evitado</span></div>
        </div>
      </section>

      {/* VISTA: AGENDAR UNA CARGA (DOBLE SELECTOR HORA/MIN) */}
      <section className={`detail-page ${activePage === 'booking' ? 'show' : ''}`} id="booking">
        <button className="back" onClick={() => setActivePage('home')}>← Inicio</button>
        <p className="eyebrow" style={{ marginTop: '28px' }}>{locationName}</p>
        <h1 style={{ fontSize: '28px', lineHeight: '1.12', margin: '4px 0' }}>Agenda tu carga</h1>
        <p className="community-note">Selecciona un día y la hora de inicio (fracciones de 15 min) para programar tu suministro.</p>
        
        <div className="section"><h2>Selecciona un día (Próxima semana)</h2></div>
        <div className="date-rail" style={{ display: 'flex', gap: '9px', overflowX: 'auto', paddingBottom: '4px' }}>
          {daysList.map((item, idx) => (
            <button 
              key={idx} 
              className={`date ${selectedDay.dateVal === item.dateVal ? 'selected' : ''}`} 
              onClick={() => setSelectedDay(item)}
              style={{ flex: '0 0 80px', border: '1px solid var(--line)', borderRadius: '14px', background: selectedDay.dateVal === item.dateVal ? '#1b3158' : '#171b24', color: selectedDay.dateVal === item.dateVal ? '#eff6ff' : '#aab5c4', padding: '10px 6px', fontFamily: 'inherit', cursor: 'pointer' }}
            >
              <b style={{ display: 'block', fontSize: '12px', color: 'inherit' }}>{item.label}</b>
              <span style={{ fontSize: '11px' }}>{item.text}</span>
            </button>
          ))}
        </div>

        {/* SELECTORES DE HORA Y MINUTO */}
        <div className="section"><h2>Hora de inicio</h2><span style={{ fontSize: '11px', color: 'var(--muted)' }}>Formato 24h</span></div>
        <div style={{ display: 'flex', gap: '10px', marginBottom: '16px' }}>
          {availableHoursList.length > 0 ? (
            <>
              <div style={{ flex: 1 }}>
                <select 
                  value={startHour} 
                  onChange={(e) => setStartHour(e.target.value)}
                  style={{ width: '100%', padding: '14px', borderRadius: '13px', background: '#171b24', color: '#f8fafc', border: '1px solid var(--line)', fontSize: '15px', fontWeight: 700, fontFamily: 'inherit', outline: 'none', cursor: 'pointer' }}
                >
                  {availableHoursList.map((h) => (
                    <option key={h} value={h} style={{ background: '#171b24', color: '#f8fafc' }}>
                      {h} hrs
                    </option>
                  ))}
                </select>
              </div>
              <div style={{ flex: 1 }}>
                <select 
                  value={startMinute} 
                  onChange={(e) => setStartMinute(e.target.value)}
                  style={{ width: '100%', padding: '14px', borderRadius: '13px', background: '#171b24', color: '#f8fafc', border: '1px solid var(--line)', fontSize: '15px', fontWeight: 700, fontFamily: 'inherit', outline: 'none', cursor: 'pointer' }}
                >
                  {availableMinutesList.map((m) => (
                    <option key={m} value={m} style={{ background: '#171b24', color: '#f8fafc' }}>
                      {m} min
                    </option>
                  ))}
                </select>
              </div>
            </>
          ) : (
            <p style={{ fontSize: '13px', color: '#fca5a5', padding: '10px 0', flex: 1 }}>No hay horas disponibles restantes para el día de hoy.</p>
          )}
        </div>

        {/* SELECTOR DE DURACIÓN */}
        <div className="section"><h2>Duración estimada</h2><span style={{ fontSize: '11px', color: 'var(--muted)' }}>7.2 kW máx.</span></div>
        <div className="duration-options" style={{ display: 'flex', gap: '8px', overflowX: 'auto', paddingBottom: '4px' }}>
          {[1, 2, 3, 4, 5, 6].map((h) => (
            <button 
              key={h}
              className={`duration ${totalHours === h ? 'selected' : ''}`}
              onClick={() => setTotalHours(h)}
              style={{ flex: 1, border: '1px solid var(--line)', borderRadius: '12px', background: totalHours === h ? '#eff6ff' : '#171b24', color: totalHours === h ? '#172554' : '#aab5c4', padding: '11px 4px', fontFamily: 'inherit', fontSize: '12px', fontWeight: 700, cursor: 'pointer' }}
            >
              {h} {h === 1 ? 'hora' : 'horas'}
            </button>
          ))}
        </div>

        <div className="booking-summary" style={{ marginTop: '22px', borderRadius: '18px', padding: '15px', background: '#171b24', border: '1px solid var(--line)' }}>
          <p style={{ display: 'flex', justifyContent: 'space-between', margin: '0 0 8px', color: '#94a3b8', fontSize: '12px' }}><span>Tu reserva</span><span>{selectedDay.label} · {startHour}:{startMinute} — {getEndTime()}</span></p>
          <p style={{ display: 'flex', justifyContent: 'space-between', margin: '0 0 8px', color: '#94a3b8', fontSize: '12px' }}><span>Duración</span><span>{totalHours} {totalHours === 1 ? 'hora' : 'horas'}</span></p>
          <p style={{ display: 'flex', justifyContent: 'space-between', margin: 0, color: '#e2e8f0', fontWeight: 700 }}><span>Cargador asignado</span><span>{chargerName}</span></p>
        </div>

        {reservationConfirmed && (
          <div className="booking-success show" style={{ marginTop: '14px', padding: '13px 14px', borderRadius: '13px', background: 'rgba(34,197,94,.13)', color: '#bbf7d0', fontSize: '12px', lineHeight: '1.45' }}>
            ✓ Reserva Agendada para {selectedDay.label} de {startHour}:{startMinute} a {getEndTime()}.
          </div>
        )}

        <button 
          className="primary" 
          disabled={availableHoursList.length === 0}
          onClick={handleConfirmReservation}
          style={{ marginTop: '20px', opacity: availableHoursList.length === 0 ? 0.4 : 1, cursor: availableHoursList.length === 0 ? 'not-allowed' : 'pointer' }}
        >
          Reservar
        </button>
      </section>

      {/* VISTA: LISTA DE RESERVAS */}
      <section className={`detail-page ${activePage === 'reservations' ? 'show' : ''}`} id="reservations">
        <button className="back" onClick={() => setActivePage('home')}>← Inicio</button>
        <p className="eyebrow" style={{ marginTop: '28px' }}>{locationName}</p>
        <h1 style={{ fontSize: '28px', margin: '4px 0 26px' }}>Tus reservas</h1>
        <article className="reservation-card">
          <div className="reservation-top">
            <strong>Cargador {chargerName}</strong>
            <span 
              className="reservation-status" 
              style={{ color: getStatusColor(reservationData.status).color, background: getStatusColor(reservationData.status).bg }}
            >
              {reservationData.status}
            </span>
          </div>
          <div className="reservation-time">{reservationData.time}</div>
          <div className="reservation-meta">Nivel 1 · Parqueadero de visitantes · 7,2 kW máx.</div>
          
          {/* Ocultar los botones si la reserva está Completada o Cancelada */}
          {reservationData.status === 'Reservado' && (
            <div className="reservation-actions" style={{ display: 'flex', gap: '8px', marginTop: '14px' }}>
              <button className="mini-action" onClick={() => setActivePage('booking')} style={{ border: '1px solid var(--line)', borderRadius: '10px', background: 'transparent', color: '#bfdbfe', padding: '8px 10px', cursor: 'pointer', fontWeight: 700 }}>Modificar</button>
              <button className="mini-action danger" onClick={handleCancelReservation} style={{ border: '1px solid var(--line)', borderRadius: '10px', background: 'transparent', color: '#fca5a5', padding: '8px 10px', cursor: 'pointer', fontWeight: 700 }}>Cancelar</button>
            </div>
          )}
        </article>
      </section>

      {/* VISTA: HISTORIAL */}
      <section className={`detail-page ${activePage === 'history' ? 'show' : ''}`} id="history">
        <button className="back" onClick={() => setActivePage('home')}>← Inicio</button>
        <p className="eyebrow" style={{ marginTop: '28px' }}>SEPTIEMBRE 2026</p>
        <h1 style={{ fontSize: '28px', margin: '4px 0 20px' }}>Historial de carga</h1>
        <div className="history-row">
          <div className="activity-icon">ϟ</div>
          <div><strong>{locationName} · {chargerName}</strong><p>Ayer · 20:14 — 22:03</p></div>
          <b>16.8 kWh<br/><small style={{ color: 'var(--muted)' }}>$31.080</small></b>
        </div>
      </section>

      {/* BARRA DE NAVEGACIÓN INFERIOR */}
      <nav className="nav">
        <button className={activePage === 'home' ? 'active' : ''} onClick={() => setActivePage('home')}><i>⌂</i>Inicio</button>
        <button onClick={() => setScannerOpen(true)}><i className="qr-mini" aria-hidden="true"></i>Escanear</button>
        <button className={activePage === 'reservations' ? 'active' : ''} onClick={() => setActivePage('reservations')}><i>◷</i>Reservas</button>
        <button className={activePage === 'usage' ? 'active' : ''} onClick={() => setActivePage('usage')}><i>⌁</i>Consumo</button>
      </nav>

      {/* MODAL ESCANER QR */}
      {scannerOpen && (
        <section className="modal open" role="dialog">
          <button className="modal-close" onClick={() => setScannerOpen(false)}>×</button>
          <h2>Escanea el QR<br/>del cargador</h2>
          <p>Apunta la cámara al código ubicado en el frente del equipo para identificarlo y conectar.</p>
          <div className="scanner">
            <div className="scanline"></div>
            <div className="scan-code" style={{ fontFamily: 'DM Mono', fontSize: '11px', textAlign: 'center', color: '#bfdbfe', marginTop: '110px' }}>{scanState.text}</div>
          </div>
          {scanState.resultShow && (
            <div className="scan-result show" style={{ margin: '4px 0 18px', padding: '12px', borderRadius: '13px', background: 'rgba(34,197,94,.13)', fontSize: '12px', color: '#bbf7d0' }}>
              ✓ {chargerName} encontrado · Parqueadero Central
            </div>
          )}
          <button className="primary" onClick={() => {
            if (scanState.btnText === 'Simular escaneo') {
              setScanState({ text: `QR: VOLTA / ${chargerName}`, resultShow: true, btnText: 'Conectar cargador' });
            } else {
              setScannerOpen(false);
              setStatusText(`${chargerName} listo para cargar`);
              setActivePage('home');
              setScanState({ text: 'BUSCANDO CÓDIGO…', resultShow: false, btnText: 'Simular escaneo' });
            }
          }}>
            {scanState.btnText}
          </button>
          <button className="link" onClick={() => setManualEntryShow(!manualEntryShow)} style={{ margin: '16px auto 0', border: 0, background: 'none', color: '#60a5fa', fontWeight: 700, cursor: 'pointer' }}>
            Ingresar código manualmente
          </button>
          {manualEntryShow && (
            <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
              <input 
                value={manualCode} 
                onChange={e => setManualCode(e.target.value)} 
                placeholder="Ej. VC-0821" 
                style={{ minWidth: 0, flex: 1, border: '1px solid var(--line)', borderRadius: '11px', background: '#171b24', color: '#f8fafc', padding: '12px', fontFamily: 'DM Mono', fontSize: '12px' }}
              />
              <button 
                onClick={() => {
                  const codeClean = manualCode.trim().toUpperCase();
                  if (/^VC-\d{4}$/.test(codeClean)) {
                    setScannerOpen(false);
                    setChargerName(codeClean);
                    setStatusText(`${codeClean} listo para cargar`);
                    setActivePage('home');
                  } else {
                    alert('Ingresa un código válido, por ejemplo VC-0821.');
                  }
                }}
                style={{ border: 0, borderRadius: '11px', background: '#3b82f6', color: '#fff', padding: '0 13px', fontWeight: 700, cursor: 'pointer' }}
              >
                Conectar
              </button>
            </div>
          )}
        </section>
      )}

      {/* MODAL DE CONFIRMACIÓN */}
      {confirmOpen && (
        <section className="modal open" role="dialog">
          <div className="confirm-panel">
            <h2>{confirmConfig.title}</h2>
            <p>{confirmConfig.text}</p>
            <div className="confirm-actions">
              <button className="primary secondary" onClick={() => setConfirmOpen(false)}>Volver</button>
              <button className="primary danger-primary" onClick={() => { setConfirmOpen(false); if (confirmConfig.action) confirmConfig.action(); }}>{confirmConfig.label}</button>
            </div>
          </div>
        </section>
      )}
    </main>
  );
}