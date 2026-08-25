/* Elderly Care System dashboard - Flask API integration */

const API = {
    async request(path, options = {}) {
        const response = await fetch(path, {
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
            ...options
        });
        const body = await response.json().catch(() => ({}));
        if (response.status === 401 && path !== '/api/auth/login') {
            showLogin();
        }
        if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
        return body;
    },
    login: openId => API.request('/api/auth/login', { method: 'POST', body: JSON.stringify({ openId }) }),
    residents: () => API.request('/api/residents'),
    createResident: payload => API.request('/api/patients', { method: 'POST', body: JSON.stringify(payload) }),
    medications: () => API.request('/api/medications'),
    notifications: () => API.request('/api/notifications')
};

let patients = [];
let medications = [];

function showLogin() {
    if ($('#loginPanel').length) return;
    $('body').prepend(`<div id="loginPanel" class="position-fixed top-0 start-0 w-100 h-100 d-flex align-items-center justify-content-center" style="z-index:2000;background:rgba(0,0,0,.55)">
        <form id="loginForm" class="card p-4 shadow-lg" style="min-width:320px"><h5 class="fw-bold mb-3">تسجيل الدخول</h5>
            <label class="form-label">معرّف المستخدم</label><input id="openId" class="form-control mb-3" value="test-user-001" required>
            <button class="btn btn-primary" type="submit">دخول</button><div id="loginError" class="text-danger mt-2"></div>
        </form></div>`);
    $('#loginForm').on('submit', async event => {
        event.preventDefault();
        try { await API.login($('#openId').val().trim()); window.location.reload(); }
        catch (error) { $('#loginError').text(error.message); }
    });
}

function showError(error) {
    console.error(error);
    $('.dashboard-error').remove();
    $('#content').prepend(`<div class="dashboard-error alert alert-danger" role="alert">${error.message || 'تعذر الاتصال بالخادم'}</div>`);
}

function ageFromDate(dateOfBirth) {
    if (!dateOfBirth) return '—';
    const birth = new Date(dateOfBirth);
    if (Number.isNaN(birth.getTime())) return '—';
    const today = new Date();
    let age = today.getFullYear() - birth.getFullYear();
    if (today < new Date(today.getFullYear(), birth.getMonth(), birth.getDate())) age--;
    return age;
}

function patientCondition(patient) {
    return (patient.notes || '').replace(/^Condition:\s*/i, '') || 'غير مسجل';
}

const UI = {
    renderPatients() {
        const list = $('#patientsList');
        if (!list.length) return;
        list.empty();
        patients.forEach(patient => list.append(`
            <div class="col-xl-4 col-md-6 mb-4"><div class="card h-100"><div class="card-body">
                <div class="d-flex align-items-center mb-3">
                    <div class="patient-avatar d-flex align-items-center justify-content-center bg-primary text-white"><i class="fas fa-user"></i></div>
                    <div><h5 class="mb-0 fw-bold">${patient.name}</h5><small class="text-muted">العمر: ${ageFromDate(patient.dateOfBirth)} سنة</small></div>
                </div>
                <p class="mb-2"><strong>الأمراض:</strong> ${patientCondition(patient)}</p>
                <div class="d-flex justify-content-between align-items-center mt-3"><span class="badge bg-success">مستقر</span>
                    <button class="btn btn-sm btn-light text-primary" onclick="viewPatient(${patient.id})"><i class="fas fa-eye"></i></button>
                </div>
            </div></div></div>`));
        if (!patients.length) list.append('<div class="col-12"><p class="text-muted">لا توجد بيانات مرضى.</p></div>');
    },
    renderMeds() {
        const table = $('#medsTableBody');
        if (!table.length) return;
        table.empty();
        medications.forEach(medication => table.append(`<tr><td>—</td><td>${medication.name}</td><td>${medication.dosage || '—'}</td><td>${medication.form || '—'}</td><td>—</td></tr>`));
        if (!medications.length) table.append('<tr><td colspan="5" class="text-center text-muted p-4">لا توجد أدوية مسجلة.</td></tr>');
    },
    async updateNotifCount() {
        try { $('.notif-badge').text((await API.notifications()).notifications.length); } catch (error) { showError(error); }
    }
};

window.viewPatient = id => {
    sessionStorage.setItem('currentPatientId', id);
    window.location.href = 'patient_details.html';
};

async function loadDashboardData() {
    try {
        const [residentData, medicationData] = await Promise.all([API.residents(), API.medications()]);
        patients = residentData.residents || [];
        medications = medicationData.medications || [];
        UI.renderPatients();
        UI.renderMeds();
        await UI.updateNotifCount();
        const select = $('#medPatientId');
        if (select.length) {
            select.empty().append('<option value="">اختر المريض (اختياري)</option>');
            patients.forEach(patient => select.append(`<option value="${patient.id}">${patient.name}</option>`));
        }
    } catch (error) { showError(error); }
}

window.initNotifications = async () => {
    try {
        const data = await API.notifications();
        const list = $('#notifList').empty();
        if (!data.notifications.length) list.append('<div class="text-center p-5"><i class="fas fa-bell-slash fa-3x text-muted mb-3"></i><p class="text-muted">لا توجد إشعارات جديدة</p></div>');
        data.notifications.forEach(notification => list.append(`<div class="card mb-3 border-start border-4 border-warning"><div class="card-body d-flex justify-content-between align-items-center"><div><h6 class="mb-1 fw-bold">${notification.message}</h6><small class="text-muted"><i class="far fa-clock me-1"></i>${notification.sentAt || ''}</small></div><i class="fas fa-exclamation-circle text-warning"></i></div></div>`));
        $('.notif-badge').text(data.notifications.length);
    } catch (error) { showError(error); }
};

window.initPatientDetail = async () => {
    const id = Number(sessionStorage.getItem('currentPatientId'));
    if (!id) return window.location.href = 'index.html';
    try {
        const [data, scheduleData, timeData] = await Promise.all([API.residents(), API.request('/api/medication-schedules'), API.request('/api/medication-schedule-times')]);
        const patient = (data.residents || []).find(item => item.id === id);
        if (!patient) return window.location.href = 'index.html';
        $('#detName').text(patient.name);
        $('#detAge').text(`العمر: ${ageFromDate(patient.dateOfBirth)} سنة`);
        $('#detStatus').text('مستقر');
        $('#detDiseases').text(patientCondition(patient));
        $('#detImg').attr('src', 'https://via.placeholder.com/150');
        const schedules = (scheduleData.schedules || []).filter(item => item.residentId === id);
        const times = timeData.schedule_times || [];
        const list = $('#detMedsList').empty();
        if (!schedules.length) list.html('<p class="text-muted">لا توجد أدوية مجدولة.</p>');
        schedules.forEach(schedule => {
            const scheduleTimes = times.filter(time => time.scheduleId === schedule.id).map(time => time.timeOfDay).join('، ');
            list.append(`<div class="d-flex justify-content-between align-items-center p-3 border rounded-3 mb-2 bg-light"><div><h6 class="mb-1 fw-bold">${schedule.medication_name || 'دواء'}</h6><small class="text-muted">${schedule.frequency || ''} ${scheduleTimes ? `- ${scheduleTimes}` : ''}</small></div><i class="fas fa-clock text-primary"></i></div>`);
        });
        UI.updateNotifCount();
    } catch (error) { showError(error); }
};

$(document).ready(() => {
    $('#sidebarCollapse').on('click', () => $('#sidebar, #content').toggleClass('active'));
    if ($('#patientsList').length || $('#medsTableBody').length) loadDashboardData();

    $('#addPatientForm').on('submit', async function (event) {
        event.preventDefault();
        try {
            await API.createResident({ name: $('#pName').val(), age: Number($('#pAge').val()), condition: $('#pDiseases').val() });
            await loadDashboardData();
            bootstrap.Modal.getOrCreateInstance(document.getElementById('addPatientModal')).hide();
            this.reset();
        } catch (error) { showError(error); }
    });

    $('#addMedForm').on('submit', async function (event) {
        event.preventDefault();
        try {
            await API.request('/api/medications', { method: 'POST', body: JSON.stringify({ name: $('#medName').val(), dosage: $('#medDose').val() }) });
            await loadDashboardData();
            bootstrap.Modal.getOrCreateInstance(document.getElementById('addMedModal')).hide();
            this.reset();
        } catch (error) { showError(error); }
    });
});
