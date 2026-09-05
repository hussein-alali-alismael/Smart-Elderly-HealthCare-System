import { useEffect, useMemo, useState } from 'react';
import { NavLink, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import API from './lib/api';

const emptyResidentForm = { name: '', dateOfBirth: '', notes: '', condition: '' };
const emptyMedicationForm = {
  name: '',
  dosage: '',
  form: '',
  manufacturer: '',
  side_effects: '',
  instructions: '',
  contraindications: '',
};
const youngestResidentDate = (() => {
  const date = new Date();
  date.setFullYear(date.getFullYear() - 50);
  return date.toISOString().slice(0, 10);
})();

function Brand({ mobile = false, marginBottom }) {
  return (
    <div className="brand" style={{ marginBottom: marginBottom ?? (mobile ? '0' : '36px') }}>
      <div className="brand-logo">
        <img src="/logo.svg" alt="نظام الرعاية الصحية الذكي لكبار السن" />
      </div>
    </div>
  );
}

function TopBar({ section, title, userLabel, action, onMenuOpen, backAction }) {
  return (
    <div className="topbar">
      <div className="topbar-title">
        <span>{section}</span>
        <strong>{title}</strong>
      </div>
      <div className="topbar-actions">
        {userLabel && <div className="user-chip">{userLabel}</div>}
        {action}
      </div>
      {backAction}
      <button className="menu-button" type="button" onClick={() => onMenuOpen(true)} aria-label="فتح القائمة">
        <span />
        <span />
        <span />
      </button>
    </div>
  );
}

function AuthPage({ mode }) {
  const navigate = useNavigate();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError('');
    setLoading(true);

    const form = new FormData(e.target);
    const values = Object.fromEntries(form.entries());

    try {
      if (mode === 'login') {
        const res = await API.login(values.openId || values.email || values.userId, values.password);
        if (res?.error) throw new Error(res.error);
      } else {
        const res = await API.signup(values.name, values.email, values.password);
        if (res?.error) throw new Error(res.error);
      }
      navigate('/');
    } catch (err) {
      setError(err.message || 'حدث خطأ أثناء العملية');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-screen">
      <div className="auth-art">
        <div>
          <Brand />
          <h1>مراقبة ذكية <em>لرعاية أفضل</em></h1>
          <p>
            متابعة المسنين، تنظيم الأدوية، مراقبة المواعيد، وتتبع حالة كل مسن في منصة واحدة متكاملة.
          </p>
        </div>
      </div>

      <div className="auth-card">
        <div className="auth-card-logo">
          <img src="/logo.svg" alt="logo" />
        </div>
        <div className="eyebrow">{mode === 'login' ? 'تسجيل الدخول' : 'إنشاء حساب'}</div>
        <h2>{mode === 'login' ? 'مرحباً بعودتك' : 'إنشاء حساب جديد'}</h2>
        <p className="muted">{mode === 'login' ? 'لوحة التحكم' : 'حساب مقدم الرعاية'}</p>

        <form className="auth-form" onSubmit={submit}>
          {mode === 'signup' && (
            <label>
              الاسم الكامل
              <input name="name" type="text" required />
            </label>
          )}

          <label>
            {mode === 'login' ? 'البريد الإلكتروني أو معرف المستخدم' : 'البريد الإلكتروني'}
            <input
              name={mode === 'login' ? 'openId' : 'email'}
              type={mode === 'login' ? 'text' : 'email'}
              required
            />
          </label>

          <label>
            كلمة المرور
            <input name="password" type="password" minLength="8" required />
          </label>

          {error && <div className="form-error">{error}</div>}

          <button className="primary-button full-button" type="submit" disabled={loading}>
            {loading ? 'جارٍ...' : mode === 'login' ? 'تسجيل الدخول' : 'إنشاء الحساب'}
          </button>
        </form>

        <p className="auth-switch">
          {mode === 'login' ? 'ليس لديك حساب؟' : 'لديك حساب؟'}
          <NavLink to={mode === 'login' ? '/signup' : '/login'} className="nav-link">
            {mode === 'login' ? 'إنشاء حساب' : 'تسجيل الدخول'}
          </NavLink>
        </p>
      </div>
    </div>
  );
}

function DashboardLayout() {
  const navigate = useNavigate();
  const [residents, setResidents] = useState([]);
  const [medications, setMedications] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [scheduleTimes, setScheduleTimes] = useState([]);
  const [error, setError] = useState('');
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const closeMobileMenu = () => setMobileMenuOpen(false);

  const loadAll = async () => {
    try {
      const [residentRes, medRes, notifRes, scheduleRes, timeRes] = await Promise.all([
        API.getResidents(),
        API.getMedications(),
        API.getNotifications(),
        API.getSchedules(),
        API.getScheduleTimes(),
      ]);

      setResidents(residentRes.residents || residentRes.data || []);
      setMedications(medRes.medications || medRes.data || []);
      setNotifications(notifRes.notifications || notifRes.data || []);
      setSchedules(scheduleRes.schedules || scheduleRes.data || []);
      setScheduleTimes(timeRes.schedule_times || timeRes.data || []);
    } catch (err) {
      setError(err.message || 'تعذر تحميل البيانات');
    }
  };

  useEffect(() => {
    loadAll();
    const timer = window.setInterval(loadAll, 10000);
    return () => window.clearInterval(timer);
  }, []);

  async function handleLogout() {
    try {
      await API.logout();
    } finally {
      navigate('/login');
    }
  }

  return (
    <div className="app-shell">
      {mobileMenuOpen && (
        <div className="mobile-nav-overlay" onClick={closeMobileMenu}>
          <div className="mobile-nav-panel" onClick={(e) => e.stopPropagation()}>
            <div className="mobile-nav-header">
              <Brand mobile />
              <button className="close-btn" type="button" onClick={closeMobileMenu} aria-label="إغلاق القائمة">×</button>
            </div>

            <nav className="mobile-nav-list">
              <NavLink to="/" end onClick={closeMobileMenu} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <span>👥</span> إدارة المسنين
              </NavLink>
              <NavLink to="/medications" onClick={closeMobileMenu} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <span>💊</span> الأدوية
              </NavLink>
              <NavLink to="/camera" onClick={closeMobileMenu} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <span>📹</span> بث الكاميرا
              </NavLink>
              <NavLink to="/notifications" onClick={closeMobileMenu} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <span>🔔</span> الإشعارات <b>{notifications.length}</b>
              </NavLink>
            </nav>

            <button className="secondary-button danger" onClick={() => { handleLogout(); closeMobileMenu(); }} style={{ width: '100%' }}>
              <span aria-hidden="true">⎋</span> تسجيل الخروج
            </button>
          </div>
        </div>
      )}

      <aside className="sidebar">
        <Brand marginBottom="10px" />

        <div className="workspace-label">Workspace</div>

        <nav>
          <NavLink to="/" end className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <span>👥</span> إدارة المسنين
          </NavLink>
          <NavLink to="/medications" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <span>💊</span> الأدوية
          </NavLink>
          <NavLink to="/camera" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <span>📹</span> بث الكاميرا
          </NavLink>
          <NavLink to="/notifications" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <span>🔔</span> الإشعارات <b>{notifications.length}</b>
          </NavLink>

          <div className="sidebar-footer">
            <button className="secondary-button danger" onClick={handleLogout} style={{ width: '100%' }}>
              <span aria-hidden="true">⎋</span> تسجيل الخروج
            </button>
          </div>
        </nav>
      </aside>

      <main className="main-content">
        {error && <div className="alert">{error}</div>}
        <Routes>
          <Route path="/" element={<ResidentsPage residents={residents} refresh={loadAll} setMobileMenuOpen={setMobileMenuOpen} />} />
          <Route path="/patients/:residentId" element={<PatientProfilePage residents={residents} medications={medications} schedules={schedules} scheduleTimes={scheduleTimes} refresh={loadAll} setMobileMenuOpen={setMobileMenuOpen} />} />
          <Route path="/medications" element={<MedicationsPage medications={medications} residents={residents} schedules={schedules} scheduleTimes={scheduleTimes} refresh={loadAll} setMobileMenuOpen={setMobileMenuOpen} />} />
          <Route path="/camera" element={<CameraPage setMobileMenuOpen={setMobileMenuOpen} />} />
          <Route path="/notifications" element={<NotificationsPage notifications={notifications} setMobileMenuOpen={setMobileMenuOpen} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function ResidentsPage({ residents, refresh, setMobileMenuOpen }) {
  const navigate = useNavigate();
  const [form, setForm] = useState(emptyResidentForm);
  const [editingId, setEditingId] = useState(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);

  function openCreateModal() {
    setEditingId(null);
    setForm(emptyResidentForm);
    setMessage('');
    setIsModalOpen(true);
  }

  function fillForm(resident) {
    setEditingId(resident.id);
    setForm({
      name: resident.name || '',
      dateOfBirth: resident.dateOfBirth || '',
      notes: resident.notes || '',
      condition: resident.condition || resident.notes || '',
    });
    setMessage('');
    setIsModalOpen(true);
  }

  async function submitResident(e) {
    e.preventDefault();
    setSaving(true);
    setMessage('');

    const payload = {
      name: form.name,
      dateOfBirth: form.dateOfBirth || undefined,
      notes: form.notes || undefined,
      condition: form.condition || undefined,
    };

    try {
      if (editingId) {
        await API.updateResident(editingId, payload);
        setMessage('تم تحديث المسن بنجاح');
      } else {
        await API.createResident(payload);
        setMessage('تم إضافة المسن بنجاح');
      }
      setForm(emptyResidentForm);
      setEditingId(null);
      setIsModalOpen(false);
      await refresh();
    } catch (err) {
      setMessage(err.message || 'تعذر حفظ المسن');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id) {
    if (!window.confirm('هل تريد حذف هذا المسن؟')) return;
    try {
      await API.deleteResident(id);
      await refresh();
    } catch (err) {
      setMessage(err.message || 'تعذر حذف المسن');
    }
  }

  return (
    <>
      <TopBar section="لوحة التحكم" title="إدارة المسنين" userLabel="👤 مسؤول النظام" action={<button className="primary-button" onClick={openCreateModal}>+ إضافة مسن</button>} onMenuOpen={setMobileMenuOpen} />

      <div className="resident-grid">
        {residents.map((resident) => {
          const initials = (resident.name || 'مسن')
            .split(' ')
            .filter(Boolean)
            .slice(0, 2)
            .map((part) => part[0])
            .join('')
            .toUpperCase() || 'م';

          return (
            <div key={resident.id} className="resident-card card">
              <div className="resident-card-top">
                <div className="avatar">{initials}</div>
                <button className="icon-btn" title="ملف المسن" onClick={() => navigate(`/patients/${resident.id}`)}>👤</button>
              </div>

              <div className="resident-card-body">
                <h3>{resident.name || 'مسن'}</h3>
                <p className="muted">{resident.dateOfBirth ? `تاريخ الميلاد: ${resident.dateOfBirth}` : 'تاريخ الميلاد غير مسجل'}</p>
                <p className="muted">{resident.condition || resident.notes || 'لا توجد حالة مسجلة'}</p>
              </div>

              <div className="resident-card-actions">
                <button className="btn btn-icon btn-secondary" title="عرض الملف" onClick={() => navigate(`/patients/${resident.id}`)} aria-label="عرض الملف">👁️</button>
                <button className="btn btn-icon btn-secondary" title="تعديل" onClick={() => fillForm(resident)} aria-label="تعديل">✏️</button>
                <button className="btn btn-icon btn-danger" title="حذف" onClick={() => handleDelete(resident.id)} aria-label="حذف">🗑️</button>
              </div>
            </div>
          );
        })}
      </div>

      {isModalOpen && (
        <div className="modal-overlay" onClick={() => setIsModalOpen(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{editingId ? 'تعديل بيانات المسن' : 'إضافة مسن جديد'}</h3>
              <button type="button" className="close-btn" onClick={() => setIsModalOpen(false)}>×</button>
            </div>

            <form className="form" onSubmit={submitResident}>
              <label>
                الاسم الكامل
                <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              </label>
              <label>
                تاريخ الميلاد
                <input type="date" max={youngestResidentDate} value={form.dateOfBirth} onChange={(e) => setForm({ ...form, dateOfBirth: e.target.value })} required />
              </label>
              <label>
                الحالة/الحالة الطبية
                <input value={form.condition} onChange={(e) => setForm({ ...form, condition: e.target.value })} placeholder="مثال: سكري / ضغط" />
              </label>
              <label>
                الملاحظات
                <textarea rows="4" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="ملاحظات إضافية" />
              </label>

              {message && <div className="toast-message">{message}</div>}

              <div className="inline-actions">
                <button className="btn btn-primary" type="submit" disabled={saving}>
                  {saving ? 'جارٍ الحفظ...' : editingId ? 'حفظ التعديلات' : 'إضافة مسن جديد'}
                </button>
                <button type="button" className="btn btn-secondary" onClick={() => { setIsModalOpen(false); setEditingId(null); setForm(emptyResidentForm); setMessage(''); }}>
                  إلغاء
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}

function MedicationsPage({ medications, residents, schedules, scheduleTimes, refresh, setMobileMenuOpen }) {
  const [form, setForm] = useState({
    ...emptyMedicationForm,
    residentId: '',
    frequency: 'daily',
    startDate: '',
    endDate: '',
    notes: '',
    times: ['08:00'],
  });
  const [editingId, setEditingId] = useState(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);

  const scheduleMeta = useMemo(() => {
    const grouped = {};
    scheduleTimes.forEach((time) => {
      if (!grouped[time.scheduleId]) grouped[time.scheduleId] = [];
      grouped[time.scheduleId].push(time);
    });
    return grouped;
  }, [scheduleTimes]);

  function openCreateMedicationModal() {
    setEditingId(null);
    setForm({
      ...emptyMedicationForm,
      residentId: '',
      frequency: 'daily',
      startDate: '',
      endDate: '',
      notes: '',
      times: ['08:00'],
    });
    setMessage('');
    setIsModalOpen(true);
  }

  function fillMedicationForm(med) {
    setEditingId(med.id);
    setForm({
      name: med.name || '',
      dosage: med.dosage || '',
      form: med.form || '',
      manufacturer: med.manufacturer || '',
      side_effects: med.sideEffects || '',
      instructions: med.instructions || '',
      contraindications: med.contraindications || '',
      residentId: '',
      frequency: 'daily',
      startDate: '',
      endDate: '',
      notes: '',
      times: ['08:00'],
    });
    setMessage('');
    setIsModalOpen(true);
  }

  async function submitMedication(e) {
    e.preventDefault();
    setSaving(true);
    setMessage('');

    try {
      const payload = {
        name: form.name,
        dosage: form.dosage,
        form: form.form,
        manufacturer: form.manufacturer,
        side_effects: form.side_effects,
        instructions: form.instructions,
        contraindications: form.contraindications,
      };

      let createdMedication = null;

      if (editingId) {
        createdMedication = await API.updateMedication(editingId, payload);
        setMessage('تم تحديث الدواء بنجاح');
      } else {
        createdMedication = await API.createMedication(payload);
        setMessage('تم إضافة الدواء بنجاح');
      }

      const medicationId = editingId || createdMedication?.id || createdMedication?.data?.id;

      if (form.residentId && medicationId && form.startDate) {
        const createdSchedule = await API.createSchedule({
          residentId: Number(form.residentId),
          medicationId: Number(medicationId),
          frequency: form.frequency,
          startDate: form.startDate,
          endDate: form.endDate || null,
          notes: form.notes,
          isActive: true,
        });

        const scheduleId = createdSchedule?.id || createdSchedule?.data?.id;
        if (scheduleId) {
          await Promise.all(
            form.times.filter(Boolean).map((timeOfDay) => API.createScheduleTime(scheduleId, { timeOfDay }))
          );
        }
      }

      setForm({
        ...emptyMedicationForm,
        residentId: '',
        frequency: 'daily',
        startDate: '',
        endDate: '',
        notes: '',
        times: ['08:00'],
      });
      setEditingId(null);
      setIsModalOpen(false);
      await refresh();
    } catch (err) {
      setMessage(err.message || 'تعذر حفظ الدواء');
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteMedication(id) {
    if (!window.confirm('هل تريد حذف هذا الدواء؟')) return;
    try {
      await API.deleteMedication(id);
      await refresh();
    } catch (err) {
      setMessage(err.message || 'تعذر حذف الدواء');
    }
  }

  async function handleDeleteSchedule(scheduleId) {
    if (!window.confirm('هل تريد حذف هذا الجدول؟')) return;
    try {
      await API.deleteSchedule(scheduleId);
      await refresh();
    } catch (err) {
      setMessage(err.message || 'تعذر حذف الجدول');
    }
  }

  async function handleDeleteTime(timeId) {
    if (!window.confirm('هل تريد حذف هذا الوقت؟')) return;
    try {
      await API.deleteScheduleTime(timeId);
      await refresh();
    } catch (err) {
      setMessage(err.message || 'تعذر حذف الوقت');
    }
  }

  return (
    <>
      <TopBar section="لوحة التحكم" title="إدارة الأدوية" userLabel="💊 إدارة العلاج" action={<button className="primary-button" onClick={openCreateMedicationModal}>+ إضافة دواء</button>} onMenuOpen={setMobileMenuOpen} />

      <section className="card list-panel medication-list-panel">
        <h3>قائمة الأدوية</h3>
        <div className="stack-list">
          {medications.map((med) => (
            <div key={med.id} className="list-item">
              <div>
                <strong>{med.name}</strong>
                <div className="muted">{med.dosage || 'بدون جرعة'} · {med.form || 'بدون شكل'}</div>
                <div className="muted">{med.manufacturer || 'بدون مصنع'}</div>
              </div>
              <div className="item-actions">
                <button className="btn btn-icon btn-secondary" title="تعديل" onClick={() => fillMedicationForm(med)} aria-label="تعديل">✏️</button>
                <button className="btn btn-icon btn-danger" title="حذف" onClick={() => handleDeleteMedication(med.id)} aria-label="حذف">🗑️</button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {isModalOpen && (
        <div className="modal-overlay" onClick={() => setIsModalOpen(false)}>
          <div className="modal-card modal-card-wide" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{editingId ? 'تعديل دواء' : 'إضافة دواء'}</h3>
              <button type="button" className="close-btn" onClick={() => setIsModalOpen(false)}>×</button>
            </div>
            <form className="form" onSubmit={submitMedication}>
              <div className="two-column">
                <label>
                  اسم الدواء
                  <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
                </label>
                <label>
                  المسن
                  <select value={form.residentId} onChange={(e) => setForm({ ...form, residentId: e.target.value })}>
                    <option value="">بدون ربط مباشر</option>
                    {residents.map((resident) => (
                      <option key={resident.id} value={resident.id}>{resident.name}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="two-column">
                <label>
                  الجرعة
                  <input value={form.dosage} onChange={(e) => setForm({ ...form, dosage: e.target.value })} />
                </label>
                <label>
                  الشكل
                  <input value={form.form} onChange={(e) => setForm({ ...form, form: e.target.value })} />
                </label>
              </div>
              <label>
                المصنع
                <input value={form.manufacturer} onChange={(e) => setForm({ ...form, manufacturer: e.target.value })} />
              </label>
              <label>
                الآثار الجانبية
                <textarea rows="3" value={form.side_effects} onChange={(e) => setForm({ ...form, side_effects: e.target.value })} />
              </label>
              <label>
                التعليمات
                <textarea rows="3" value={form.instructions} onChange={(e) => setForm({ ...form, instructions: e.target.value })} />
              </label>
              <label>
                موانع الاستخدام
                <textarea rows="3" value={form.contraindications} onChange={(e) => setForm({ ...form, contraindications: e.target.value })} />
              </label>

              <div className="divider" />

              <div className="two-column">
                <label>
                  التكرار
                  <select value={form.frequency} onChange={(e) => setForm({ ...form, frequency: e.target.value })}>
                    <option value="daily">يومياً</option>
                    <option value="twice-daily">مرتين يومياً</option>
                    <option value="as-needed">عند الحاجة</option>
                    <option value="weekly">أسبوعياً</option>
                  </select>
                </label>
                <label>
                  تاريخ البداية
                  <input type="date" value={form.startDate} onChange={(e) => setForm({ ...form, startDate: e.target.value })} />
                </label>
              </div>

              <label>
                تاريخ النهاية
                <input type="date" value={form.endDate} onChange={(e) => setForm({ ...form, endDate: e.target.value })} />
              </label>
              <label>
                ملاحظات الجدول
                <textarea rows="3" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              </label>

              <div>
                <div className="time-header">
                  <strong>أوقات الدواء</strong>
                  <button type="button" className="btn btn-secondary tiny-btn" onClick={() => setForm({ ...form, times: [...form.times, '08:00'] })}>+ إضافة وقت</button>
                </div>
                <div className="time-stack">
                  {form.times.map((time, index) => (
                    <div key={`${time}-${index}`} className="time-row">
                      <input
                        type="time"
                        value={time}
                        onChange={(e) => {
                          const next = [...form.times];
                          next[index] = e.target.value;
                          setForm({ ...form, times: next });
                        }}
                      />
                      {form.times.length > 1 && (
                        <button type="button" className="btn btn-danger tiny-btn" onClick={() => {
                          const next = form.times.filter((_, i) => i !== index);
                          setForm({ ...form, times: next.length ? next : ['08:00'] });
                        }}>
                          حذف
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {message && <div className="toast-message">{message}</div>}

              <div className="inline-actions">
                <button className="btn btn-primary" type="submit" disabled={saving}>
                  {saving ? 'جارٍ الحفظ...' : editingId ? 'حفظ التعديلات' : 'حفظ الدواء'}
                </button>
                <button type="button" className="btn btn-secondary" onClick={() => { setIsModalOpen(false); setEditingId(null); setForm({ ...emptyMedicationForm, residentId: '', frequency: 'daily', startDate: '', endDate: '', notes: '', times: ['08:00'] }); setMessage(''); }}>
                  إلغاء
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}

function CameraPage({ setMobileMenuOpen }) {
  const [falls, setFalls] = useState([]);
  const [loading, setLoading] = useState(true);
  const [cameraConfig, setCameraConfig] = useState({ stream_url: '', status_url: '' });
  const [cameraStatus, setCameraStatus] = useState('جاري التحقق...');
  const [modelStatus, setModelStatus] = useState(null);

  useEffect(() => {
    let active = true;

    async function loadFalls() {
      try {
        const data = await API.getFalls();
        const items = data?.fall_incidents || data?.data || [];
        if (active) {
          setFalls(items);
        }
      } catch (error) {
        console.error('Failed to load fall incidents for camera page', error);
        if (active) {
          setFalls([]);
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    loadFalls();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    let timer;
    let latestConfig = { stream_url: '', status_url: '' };

    async function loadCameraStatus() {
      try {
        const config = await API.getCameraConfig();
        if (!active) return;
        latestConfig = config;
        setCameraConfig(config);

        if (!config.status_url) {
          setCameraStatus('غير مُكوّن');
          return;
        }

        const response = await fetch(config.status_url, { cache: 'no-store' });
        if (!response.ok) throw new Error(`Status request failed (${response.status})`);
        const status = await response.json();
        if (active) {
          setModelStatus(status);
          setCameraStatus('متصل');
        }
      } catch (error) {
        console.error('Failed to load camera status', error);
        if (active) setCameraStatus(latestConfig.stream_url ? 'غير متصل' : 'غير مُكوّن');
      } finally {
        if (active) timer = window.setTimeout(loadCameraStatus, 5000);
      }
    }

    loadCameraStatus();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, []);

  return (
    <>
      <TopBar section="المراقبة" title="بث الكاميرا - Raspberry Pi" userLabel="📹 مراقبة مباشرة" onMenuOpen={setMobileMenuOpen} />

      <div className="camera-layout">
        <div className="card camera-card">
          <div className="camera-card-header">
            <div>
              <span className="eyebrow">المراقبة المباشرة</span>
              <h2>بث الكاميرا</h2>
            </div>
            <span className={`camera-live-pill ${cameraStatus === 'متصل' ? 'is-online' : ''}`}>
              <span className="camera-live-dot" /> {cameraStatus}
            </span>
          </div>
          <div className="camera-feed">
            {cameraConfig.stream_url ? (
              <img
                className="camera-stream-image"
                src={cameraConfig.stream_url}
                alt="بث كاميرا المراقبة"
                onLoad={() => setCameraStatus('متصل')}
                onError={() => setCameraStatus('غير متصل')}
              />
            ) : (
              <div className="camera-placeholder">
                <span>📹</span>
                <p>لم يتم إعداد رابط بث الكاميرا</p>
                <small>أضف FALL_STREAM_URL إلى ملف Flask .env</small>
              </div>
            )}
            <div className="camera-feed-legend">YOLOv8 Pose · 10 FPS · blue points = pose</div>
          </div>
        </div>

        <div className="card camera-panel">
          <h3>معلومات الاتصال</h3>
          <ul className="camera-list">
            <li>عنوان البث: {cameraConfig.stream_url || 'غير مُكوّن'}</li>
            <li>الحالة: {cameraStatus}</li>
            <li>نوع الكاميرا: Raspberry Pi Camera</li>
            <li>الموقع: غرفة المسن / الممر</li>
          </ul>
          <div className={`camera-model-status ${modelStatus?.fall ? 'is-fall' : ''}`}>
            <strong>حالة نموذج الوضعية</strong>
            <span>{modelStatus?.fall ? '⚠️ تم رصد سقوط' : modelStatus ? (modelStatus.status || 'يراقب بشكل طبيعي') : 'جاري الاتصال...'}</span>
            <small>الثقة: {modelStatus ? `${(Number(modelStatus.confidence || 0) * 100).toFixed(1)}%` : '—'} · الأشخاص: {modelStatus?.people ?? '—'}</small>
          </div>
          <button className="btn btn-primary" type="button" onClick={() => window.location.reload()}>تحديث البث</button>
        </div>
      </div>

      <div className="card" style={{ marginTop: '1.5rem' }}>
        <h3>الإشعارات</h3>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={{ textAlign: 'right', padding: '0.75rem', borderBottom: '1px solid #e5e7eb' }}>رقم</th>
                <th style={{ textAlign: 'right', padding: '0.75rem', borderBottom: '1px solid #e5e7eb' }}>الرسالة</th>
                <th style={{ textAlign: 'right', padding: '0.75rem', borderBottom: '1px solid #e5e7eb' }}>الحالة</th>
                <th style={{ textAlign: 'right', padding: '0.75rem', borderBottom: '1px solid #e5e7eb' }}>التاريخ</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan="4" style={{ padding: '1rem', textAlign: 'center' }}>جارٍ تحميل الإشعارات...</td>
                </tr>
              ) : falls.length === 0 ? (
                <tr>
                  <td colSpan="4" style={{ padding: '1rem', textAlign: 'center' }}>لا توجد إشعارات حالياً</td>
                </tr>
              ) : (
                falls.map((item) => (
                  <tr key={item.id}>
                    <td style={{ padding: '0.75rem', borderBottom: '1px solid #f3f4f6' }}>{item.id}</td>
                    <td style={{ padding: '0.75rem', borderBottom: '1px solid #f3f4f6' }}>{item.message || '—'}</td>
                    <td style={{ padding: '0.75rem', borderBottom: '1px solid #f3f4f6' }}>{item.status || '—'}</td>
                    <td style={{ padding: '0.75rem', borderBottom: '1px solid #f3f4f6' }}>{item.detectedAt || item.createdAt || '—'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function PatientProfilePage({ residents, medications, schedules, scheduleTimes, refresh, setMobileMenuOpen }) {
  const navigate = useNavigate();
  const { residentId } = useParams();
  const [profileForm, setProfileForm] = useState({
    ...emptyMedicationForm,
    medicationId: '',
    residentId: residentId || '',
    frequency: 'daily',
    startDate: '',
    endDate: '',
    notes: '',
    times: ['08:00'],
  });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [isFormOpen, setIsFormOpen] = useState(false);

  const resident = residents.find((item) => Number(item.id) === Number(residentId));
  const residentSchedules = schedules.filter((schedule) => Number(schedule.residentId) === Number(residentId));
  const residentScheduleTimes = scheduleTimes.filter((time) => residentSchedules.some((schedule) => Number(schedule.id) === Number(time.scheduleId)));

  const medicationEntries = useMemo(() => {
    return residentSchedules.map((schedule) => {
      const medication = medications.find((item) => Number(item.id) === Number(schedule.medicationId));
      return {
        schedule,
        medication,
        times: residentScheduleTimes.filter((time) => Number(time.scheduleId) === Number(schedule.id)),
      };
    }).filter((entry) => entry.medication);
  }, [medications, residentSchedules, residentScheduleTimes]);

  useEffect(() => {
    setProfileForm((current) => ({
      ...current,
      residentId: residentId || '',
    }));
  }, [residentId]);

  async function submitMedication(e) {
    e.preventDefault();
    setSaving(true);
    setMessage('');

    try {
      const medicationId = Number(profileForm.medicationId);
      if (!medicationId) {
        throw new Error('يرجى اختيار دواء من القائمة');
      }

      if (medicationId && Number(residentId)) {
        const createdSchedule = await API.createSchedule({
          residentId: Number(residentId),
          medicationId: Number(medicationId),
          frequency: profileForm.frequency,
          startDate: profileForm.startDate,
          endDate: profileForm.endDate || null,
          notes: profileForm.notes,
          isActive: true,
        });

        const scheduleId = createdSchedule?.id || createdSchedule?.data?.id;
        if (scheduleId) {
          await Promise.all(
            profileForm.times.filter(Boolean).map((timeOfDay) => API.createScheduleTime(scheduleId, { timeOfDay }))
          );
        }
      }

      setProfileForm({
        ...emptyMedicationForm,
        medicationId: '',
        residentId: residentId || '',
        frequency: 'daily',
        startDate: '',
        endDate: '',
        notes: '',
        times: ['08:00'],
      });
      setIsFormOpen(false);
      setMessage('تمت إضافة الدواء بنجاح');
      await refresh();
    } catch (err) {
      setMessage(err.message || 'تعذر حفظ الدواء');
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteSchedule(scheduleId) {
    if (!window.confirm('هل تريد حذف هذا الجدول؟')) return;
    try {
      await API.deleteSchedule(scheduleId);
      await refresh();
    } catch (err) {
      setMessage(err.message || 'تعذر حذف الجدول');
    }
  }

  async function handleDeleteTime(timeId) {
    if (!window.confirm('هل تريد حذف هذا الوقت؟')) return;
    try {
      await API.deleteScheduleTime(timeId);
      await refresh();
    } catch (err) {
      setMessage(err.message || 'تعذر حذف الوقت');
    }
  }

  if (!resident) {
    return (
      <div className="profile-empty card">
        <h2>المسن غير موجود</h2>
        <button className="btn btn-primary" onClick={() => navigate('/')}>العودة إلى قائمة المرضى</button>
      </div>
    );
  }

  return (
    <>
      <TopBar
        section="المرضى"
        title="ملف المسن"
        action={<button className="btn btn-primary" onClick={() => setIsFormOpen(true)}>+ إضافة دواء</button>}
        backAction={<button className="btn btn-secondary topbar-back" onClick={() => navigate('/')}>← العودة</button>}
        onMenuOpen={setMobileMenuOpen}
      />

      <div className="profile-layout">
        <section className="card profile-card">
          <div className="patient-header">
            <div className="avatar large-avatar">
              {(resident.name || 'مسن').split(' ').filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || 'م'}
            </div>
            <div>
              <h3>{resident.name}</h3>
              <p className="muted">#{resident.id}</p>
            </div>
          </div>

          <div className="profile-info-grid">
            <div><strong>تاريخ الميلاد:</strong> <span>{resident.dateOfBirth || 'غير محدد'}</span></div>
            <div><strong>الحالة الصحية:</strong> <span>{resident.condition || resident.notes || 'غير محددة'}</span></div>
            <div className="wide"><strong>ملاحظات:</strong> <span>{resident.notes || 'لا توجد ملاحظات'}</span></div>
          </div>
        </section>

        <section className="card profile-section">
          <div className="section-header">
            <h3>الأدوية ومواعيدها</h3>
            <button className="btn btn-primary tiny-btn" onClick={() => setIsFormOpen(true)}>إضافة دواء</button>
          </div>

          {message && <div className="toast-message">{message}</div>}

          <div className="medication-schedule-list">
            {medicationEntries.length ? medicationEntries.map(({ schedule, medication, times }) => (
              <div key={schedule.id} className="schedule-entry card-soft">
                <div className="schedule-entry-head">
                  <div>
                    <h4>{medication.name}</h4>
                    <p>{medication.dosage || 'بدون جرعة'} · {medication.form || 'بدون شكل'}</p>
                  </div>
                  <button className="btn btn-danger tiny-btn" onClick={() => handleDeleteSchedule(schedule.id)}>حذف</button>
                </div>

                <div className="schedule-extra">
                  <span>التكرار: {schedule.frequency || 'يومياً'}</span>
                  <span>تاريخ البداية: {schedule.startDate || 'غير محدد'}</span>
                  <span>تاريخ النهاية: {schedule.endDate || 'غير محدد'}</span>
                </div>

                <div className="time-badges">
                  {times.length ? times.map((time) => (
                    <span key={time.id} className="time-badge">
                      {time.timeOfDay}
                      <button type="button" onClick={() => handleDeleteTime(time.id)} aria-label="حذف الوقت">×</button>
                    </span>
                  )) : <span className="muted">لا توجد أوقات مسجلة</span>}
                </div>

                <p className="muted small-text">{schedule.notes || 'لا توجد ملاحظات'}</p>
              </div>
            )) : <div className="empty-box">لا توجد أدوية مرتبطة بهذا المسن حالياً.</div>}
          </div>
        </section>
      </div>

      {isFormOpen && (
        <div className="modal-overlay" onClick={() => setIsFormOpen(false)}>
          <div className="modal-card modal-card-wide" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>إضافة دواء للمسن</h3>
              <button type="button" className="close-btn" onClick={() => setIsFormOpen(false)}>×</button>
            </div>

            <form className="form" onSubmit={submitMedication}>
              <div className="two-column">
                <label>
                  اختيار الدواء من قاعدة البيانات
                  <select
                    value={profileForm.medicationId}
                    onChange={(e) => {
                      const selected = medications.find((medication) => Number(medication.id) === Number(e.target.value));
                      setProfileForm({
                        ...profileForm,
                        medicationId: e.target.value,
                        name: selected?.name || '',
                        dosage: selected?.dosage || '',
                        form: selected?.form || '',
                        manufacturer: selected?.manufacturer || '',
                        side_effects: selected?.sideEffects || selected?.side_effects || '',
                        instructions: selected?.instructions || '',
                        contraindications: selected?.contraindications || '',
                      });
                    }}
                    required
                  >
                    <option value="">اختر دواءً</option>
                    {medications.map((medication) => (
                      <option key={medication.id} value={medication.id}>
                        {medication.name}{medication.dosage ? ` - ${medication.dosage}` : ''}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  المسن
                  <input value={resident.name} readOnly />
                </label>
              </div>
              <div className="two-column">
                <label>
                  الجرعة
                  <input value={profileForm.dosage} readOnly />
                </label>
                <label>
                  الشكل
                  <input value={profileForm.form} readOnly />
                </label>
              </div>
              <label>
                المصنع
                <input value={profileForm.manufacturer} readOnly />
              </label>
              <label>
                الآثار الجانبية
                <textarea rows="3" value={profileForm.side_effects} readOnly />
              </label>
              <label>
                التعليمات
                <textarea rows="3" value={profileForm.instructions} readOnly />
              </label>
              <label>
                موانع الاستخدام
                <textarea rows="3" value={profileForm.contraindications} readOnly />
              </label>

              <div className="divider" />

              <div className="two-column">
                <label>
                  التكرار
                  <select value={profileForm.frequency} onChange={(e) => setProfileForm({ ...profileForm, frequency: e.target.value })}>
                    <option value="daily">يومياً</option>
                    <option value="twice-daily">مرتين يومياً</option>
                    <option value="as-needed">عند الحاجة</option>
                    <option value="weekly">أسبوعياً</option>
                  </select>
                </label>
                <label>
                  تاريخ البداية
                  <input type="date" value={profileForm.startDate} onChange={(e) => setProfileForm({ ...profileForm, startDate: e.target.value })} />
                </label>
              </div>

              <label>
                تاريخ النهاية
                <input type="date" value={profileForm.endDate} onChange={(e) => setProfileForm({ ...profileForm, endDate: e.target.value })} />
              </label>
              <label>
                ملاحظات الجدول
                <textarea rows="3" value={profileForm.notes} onChange={(e) => setProfileForm({ ...profileForm, notes: e.target.value })} />
              </label>

              <div>
                <div className="time-header">
                  <strong>أوقات الدواء</strong>
                  <button type="button" className="btn btn-secondary tiny-btn" onClick={() => setProfileForm({ ...profileForm, times: [...profileForm.times, '08:00'] })}>+ إضافة وقت</button>
                </div>
                <div className="time-stack">
                  {profileForm.times.map((time, index) => (
                    <div key={`${time}-${index}`} className="time-row">
                      <input
                        type="time"
                        value={time}
                        onChange={(e) => {
                          const next = [...profileForm.times];
                          next[index] = e.target.value;
                          setProfileForm({ ...profileForm, times: next });
                        }}
                      />
                      {profileForm.times.length > 1 && (
                        <button type="button" className="btn btn-danger tiny-btn" onClick={() => {
                          const next = profileForm.times.filter((_, i) => i !== index);
                          setProfileForm({ ...profileForm, times: next.length ? next : ['08:00'] });
                        }}>
                          حذف
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {message && <div className="toast-message">{message}</div>}

              <div className="inline-actions">
                <button className="btn btn-primary" type="submit" disabled={saving}>
                  {saving ? 'جارٍ الحفظ...' : 'حفظ الدواء'}
                </button>
                <button type="button" className="btn btn-secondary" onClick={() => { setIsFormOpen(false); setMessage(''); setProfileForm({ ...emptyMedicationForm, medicationId: '', residentId: residentId || '', frequency: 'daily', startDate: '', endDate: '', notes: '', times: ['08:00'] }); }}>
                  إلغاء
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}

function NotificationsPage({ notifications, setMobileMenuOpen }) {
  return (
    <>
      <TopBar section="التواصل" title="الإشعارات الواردة" userLabel={`🔔 ${notifications.length} إشعار`} onMenuOpen={setMobileMenuOpen} />
      <div className="grid">
        {notifications.length ? notifications.map((item) => (
          <div key={item.id} className="card patient-card">
            <div className="badge">{item.type || 'notification'}</div>
            <h4>{item.title || 'إشعار'}</h4>
            <p>{item.message || item.body || 'لا يوجد نص'}</p>
          </div>
        )) : <div className="card patient-card">لا توجد إشعارات</div>}
      </div>
    </>
  );
}

function ProtectedRoute({ children }) {
  const [authChecked, setAuthChecked] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  useEffect(() => {
    async function checkAuth() {
      try {
        const res = await API.getCurrentUser();
        setIsAuthenticated(!res?.error);
      } catch {
        setIsAuthenticated(false);
      } finally {
        setAuthChecked(true);
      }
    }

    checkAuth();
  }, []);

  if (!authChecked) return <div className="login-page"><div className="auth-card">جارٍ التحقق...</div></div>;
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<AuthPage mode="login" />} />
      <Route path="/signup" element={<AuthPage mode="signup" />} />
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <DashboardLayout />
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}
