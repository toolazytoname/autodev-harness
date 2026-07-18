// Fixture: minimal OD-style shared.js for od_ingest tests.

const TAB_ICONS = {
  home: 'home-svg',
  students: 'students-svg',
};

function tabbarHTML(active) {
  const t = (id, href, ico, label) =>
    `<a class="tab tab-${id} ico-${ico}" href="${href}" ${active === id ? 'aria-current="page"' : ''}>${label}</a>`;
  return `<nav class="tabbar">
    ${t('home', 'index.html', 'home', '首页')}
    ${t('students', 'students.html', 'students', '学员')}
  </nav>`;
}

const CLASSES = [
  { id: 'c1', name: '基础班', klass: 'lv-1' },
  { id: 'c2', name: '提高班', klass: 'lv-2' },
];

const TERMS = [
  { id: 't1', label: '25/10', date: '2025-10-18' },
  { id: 't2', label: '25/11', date: '2025-11-23' },
];

const STUDENTS = [
  /* 21 entries */
  { id: 's01', name: '小明', age: 8, classId: 'c1', className: '基础班', coaches: ['王老师'], events: { '50自': { s: [60.0, 58.0, 56.0] } } },
  { id: 's02', name: '小红', age: 9, classId: 'c2', className: '提高班', coaches: ['李老师'], events: {} },
];

function getRole() { return localStorage.getItem('yy_role') || 'coach'; }
function setRole(r) { localStorage.setItem('yy_role', r); }
function initRole() { document.body.setAttribute('data-role', getRole()); }
function toggleRole() { setRole(getRole() === 'coach' ? 'parent' : 'coach'); }