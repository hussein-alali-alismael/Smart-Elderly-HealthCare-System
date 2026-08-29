/**
 * Dashboard logic for the Elderly Care System
 * Uses the centralized API client from api.js with CSRF token support
 * Note: api.js must be loaded BEFORE this file in templates
 */

let patients = [];
let medications = [];

/**
 * Display error alert on the dashboard
 */
function showError(error) {
    console.error(error);
    $('.dashboard-error').remove();
    const message = error.message || error || 'تعذر الاتصال بالخادم';
    $('#content').prepend(`<div class="dashboard-error alert alert-danger alert-dismissible fade show" role="alert">
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    </div>`);
}

/**
 * Calculate age from date of birth
 */
function ageFromDate(dateOfBirth) {
    if (!dateOfBirth) return '—';
    const birth = new Date(dateOfBirth);
    if (Number.isNaN(birth.getTime())) return '—';
    const today = new Date();
    let age = today.getFullYear() - birth.getFullYear();
    if (today < new Date(today.getFullYear(), birth.getMonth(), birth.getDate())) age--;
    return age;
}

/**
 * Extract patient condition from notes
 */
function patientCondition(patient) {
    return (patient.notes || '').replace(/^Condition:\s*/i, '') || 'غير مسجل';
}

/**
 * UI rendering methods
 */
const UI = {
    renderPatients() {
        const list = $('#patientsList');
        if (!list.length) return;
        list.empty();
        patients.forEach(patient => list.append(`
            <div class="col-xl-4 col-md-6 mb-4">
                <div class="card h-100">
                    <div class="card-body">
                        <div class="d-flex align-items-center mb-3">
                            <div class="patient-avatar d-flex align-items-center justify-content-center bg-primary text-white">
                                <i class="fas fa-user"></i>
                            </div>
                            <div>
                                <h5 class="mb-0 fw-bold">${patient.name}</h5>
                                <small class="text-muted">العمر: ${ageFromDate(patient.dateOfBirth)} سنة</small>
                            </div>
                        </div>
                        <p class="mb-2"><strong>الأمراض:</strong> ${patientCondition(patient)}</p>
                        <div class="d-flex justify-content-between align-items-center mt-3">
                            <span class="badge bg-success">مستقر</span>
                            <div class="d-flex gap-2">
                                <button class="btn btn-sm btn-light text-primary" onclick="viewPatient(${patient.id})">
                                    <i class="fas fa-eye"></i>
                                </button>
                                <button class="btn btn-sm btn-danger" onclick="deletePatient(${patient.id})" title="حذف المريض">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `));
        if (!patients.length) {
            list.append('<div class="col-12"><p class="text-muted">لا توجد بيانات مرضى.</p></div>');
        }
    },

    renderMeds() {
        const table = $('#medsTableBody');
        if (!table.length) return;
        table.empty();
        medications.forEach(medication => table.append(`
            <tr>
                <td>—</td>
                <td>${medication.name}</td>
                <td>${medication.dosage || '—'}</td>
                <td>${medication.form || '—'}</td>
                <td>—</td>
            </tr>
        `));
        if (!medications.length) {
            table.append('<tr><td colspan="5" class="text-center text-muted p-4">لا توجد أدوية مسجلة.</td></tr>');
        }
    },

    async updateNotifCount() {
        try {
            const data = await API.notifications();
            $('.notif-badge').text((data.notifications || []).length);
        } catch (error) {
            console.error('Failed to update notification count:', error);
        }
    }
};

/**
 * Navigation to patient details page
 */
window.viewPatient = (id) => {
    sessionStorage.setItem('currentPatientId', id);
    window.location.href = 'patient_details.html';
};

window.deletePatient = async (id) => {
    const confirmed = window.confirm('هل أنت متأكد من حذف هذا المريض؟');
    if (!confirmed) return;

    try {
        await API.deleteResident(id);
        patients = patients.filter(patient => patient.id !== id);
        UI.renderPatients();
        await UI.updateNotifCount();
    } catch (error) {
        showError(error);
    }
};

/**
 * Load dashboard data (residents and medications)
 */
async function loadDashboardData() {
    try {
        const [residentData, medicationData] = await Promise.all([
            API.residents(),
            API.medications()
        ]);
        patients = residentData.residents || [];
        medications = medicationData.medications || [];
        UI.renderPatients();
        UI.renderMeds();
        await UI.updateNotifCount();

        // Update patient dropdown in add medication form
        const select = $('#medPatientId');
        if (select.length) {
            select.empty().append('<option value="">اختر المريض (اختياري)</option>');
            patients.forEach(patient => select.append(`<option value="${patient.id}">${patient.name}</option>`));
        }
    } catch (error) {
        showError(error);
    }
}

/**
 * Initialize notifications page
 */
window.initNotifications = async () => {
    try {
        const data = await API.notifications();
        const list = $('#notifList').empty();

        if (!data.notifications.length) {
            list.append(`
                <div class="text-center p-5">
                    <i class="fas fa-bell-slash fa-3x text-muted mb-3"></i>
                    <p class="text-muted">لا توجد إشعارات جديدة</p>
                </div>
            `);
        }

        data.notifications.forEach(notification => list.append(`
            <div class="card mb-3 border-start border-4 border-warning">
                <div class="card-body d-flex justify-content-between align-items-center">
                    <div>
                        <h6 class="mb-1 fw-bold">${notification.message}</h6>
                        <small class="text-muted">
                            <i class="far fa-clock me-1"></i>${notification.sentAt || ''}
                        </small>
                    </div>
                    <i class="fas fa-exclamation-circle text-warning"></i>
                </div>
            </div>
        `));

        $('.notif-badge').text(data.notifications.length);
    } catch (error) {
        showError(error);
    }
};

/**
 * Initialize patient detail page
 */
window.initPatientDetail = async () => {
    const id = Number(sessionStorage.getItem('currentPatientId'));
    if (!id) return (window.location.href = 'index.html');

    try {
        const [data, scheduleData, timeData] = await Promise.all([
            API.residents(),
            API.request('/api/medication-schedules'),
            API.request('/api/medication-schedule-times')
        ]);

        const patient = (data.residents || []).find(item => item.id === id);
        if (!patient) return (window.location.href = 'index.html');

        $('#detName').text(patient.name);
        $('#detAge').text(`العمر: ${ageFromDate(patient.dateOfBirth)} سنة`);
        $('#detStatus').text('مستقر');
        $('#detDiseases').text(patientCondition(patient));
        $('#detImg').attr('src', 'https://via.placeholder.com/150');

        const schedules = (scheduleData.schedules || []).filter(item => item.residentId === id);
        const times = timeData.schedule_times || [];
        const list = $('#detMedsList').empty();

        if (!schedules.length) {
            list.html('<p class="text-muted">لا توجد أدوية مجدولة.</p>');
        }

        schedules.forEach(schedule => {
            const scheduleTimes = times
                .filter(time => time.scheduleId === schedule.id)
                .map(time => time.timeOfDay)
                .join('، ');
            list.append(`
                <div class="d-flex justify-content-between align-items-center p-3 border rounded-3 mb-2 bg-light">
                    <div>
                        <h6 class="mb-1 fw-bold">${schedule.medication_name || 'دواء'}</h6>
                        <small class="text-muted">
                            ${schedule.frequency || ''} ${scheduleTimes ? `- ${scheduleTimes}` : ''}
                        </small>
                    </div>
                    <i class="fas fa-clock text-primary"></i>
                </div>
            `);
        });

        UI.updateNotifCount();
    } catch (error) {
        showError(error);
    }
};

/**
 * Initialize dashboard on document ready
 */
$(document).ready(() => {
    // Sidebar toggle
    $('#sidebarCollapse').on('click', () => $('#sidebar, #content').toggleClass('active'));

    // Load dashboard data
    if ($('#patientsList').length || $('#medsTableBody').length) {
        loadDashboardData();
    }

    // Add patient form submission
    $('#addPatientForm').on('submit', async function (event) {
        event.preventDefault();
        try {
            await API.createResident({
                name: $('#pName').val(),
                age: Number($('#pAge').val()),
                condition: $('#pDiseases').val()
            });
            await loadDashboardData();
            bootstrap.Modal.getOrCreateInstance(document.getElementById('addPatientModal')).hide();
            this.reset();
        } catch (error) {
            showError(error);
        }
    });

    // Add medication form submission
    $('#addMedForm').on('submit', async function (event) {
        event.preventDefault();
        try {
            await API.request('/api/medications', {
                method: 'POST',
                body: JSON.stringify({
                    name: $('#medName').val(),
                    dosage: $('#medDose').val()
                })
            });
            await loadDashboardData();
            bootstrap.Modal.getOrCreateInstance(document.getElementById('addMedModal')).hide();
            this.reset();
        } catch (error) {
            showError(error);
        }
    });
});

