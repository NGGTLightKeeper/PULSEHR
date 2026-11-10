// Copyright NGGT.LightKeeper. All Rights Reserved.

import { deleteJson, getJson, patchJson, postJson } from '../api.js';
import {
  clearErrors,
  confirmDialog,
  escHtml,
  promptDialog,
  setBusy,
  showErrors,
  toast,
  toastError
} from '../common.js';

// Roles an HR can give.
const ROLES = { employee: 'Сотрудник', hr: 'HR', admin: 'Администратор' };

// HR directory.
// Manage the department tree and the roles, departments and access of employees.
$(function initEmployeesPage() {
  let departments = [];
  let searchTimer = null;

  function departmentOptions(selected, emptyLabel) {
    const options = departments.map(function departmentOption(department) {
      const indent = '  '.repeat(department.depth);
      const isSelected = String(selected) === String(department.id) ? 'selected' : '';
      return `<option value="${department.id}" ${isSelected}>${indent}${escHtml(department.name)}</option>`;
    }).join('');
    return `<option value="">${emptyLabel}</option>${options}`;
  }


  // Departments.
  function renderDepartments() {
    $('#departments').removeClass('loading').html(departments.length
      ? departments.map(function departmentRow(department) {
        return `
          <div class="dept-row" style="padding-left:${department.depth * 22 + 4}px">
            <span class="dept-name">${escHtml(department.name)}</span>
            <span class="muted small">${department.employees} сотр.</span>
            <button type="button" class="btn btn-ghost btn-sm" data-rename="${department.id}">Переименовать</button>
            <button type="button" class="btn btn-ghost btn-sm" data-remove="${department.id}">Удалить</button>
          </div>`;
      }).join('')
      : '<div class="empty">Подразделений пока нет. Добавьте первое выше.</div>');

    $('#parentSelect').html(departmentOptions('', 'Верхний уровень'));
    const filter = $('#departmentFilter').val();
    $('#departmentFilter').html(departmentOptions(filter, 'Все подразделения'));
  }

  async function loadDepartments() {
    try {
      departments = await getJson('/api/v1/hr/departments/');
      renderDepartments();
    } catch (error) {
      toastError(error);
    }
  }


  // Employees.
  function employeeRow(user) {
    const roles = Object.keys(ROLES).map(function roleOption(role) {
      return `<option value="${role}" ${user.role === role ? 'selected' : ''}>${ROLES[role]}</option>`;
    }).join('');
    const phone = user.phone
      ? `${escHtml(user.phone)} ${user.phone_verified ? '' : '<span class="badge">не подтверждён</span>'}`
      : '<span class="muted">—</span>';
    const telegram = user.telegram_username
      ? `<span class="badge ${user.telegram_verified ? 'badge-success' : 'badge-warning'}">@${escHtml(user.telegram_username)}</span>`
      : '<span class="muted">—</span>';
    return `
      <tr data-user="${user.id}">
        <td><div class="employee-name">@${escHtml(user.username)}</div><div class="muted small">${escHtml(user.email)}</div></td>
        <td class="small">${phone}</td>
        <td>${telegram} ${user.push_enabled ? '<span class="badge badge-info">push</span>' : ''}</td>
        <td><select class="select select-sm" data-employee-field="department_id">${departmentOptions(user.department ? user.department.id : '', 'Не указано')}</select></td>
        <td><select class="select select-sm" data-employee-field="role">${roles}</select></td>
        <td><label class="check small"><input type="checkbox" data-employee-field="is_active" ${user.is_active ? 'checked' : ''}><span>Активен</span></label></td>
      </tr>`;
  }

  async function loadEmployees() {
    const params = new URLSearchParams();
    const query = String($('#search').val() || '').trim();
    if (query) {
      params.set('q', query);
    }
    if ($('#departmentFilter').val()) {
      params.set('department', $('#departmentFilter').val());
    }
    try {
      const users = await getJson(`/api/v1/hr/employees/?${params.toString()}`);
      $('#employees').html(users.length
        ? `<table class="table">
             <thead><tr><th>Сотрудник</th><th>Телефон</th><th>Каналы</th><th>Подразделение</th><th>Роль</th><th>Доступ</th></tr></thead>
             <tbody>${users.map(employeeRow).join('')}</tbody>
           </table>`
        : '<div class="empty">Никого не нашлось.</div>');
    } catch (error) {
      toastError(error);
    }
  }


  // Events.
  $('#departmentForm').on('submit', async function onAddDepartment(event) {
    event.preventDefault();
    const $form = $(this);
    const $button = $form.find('button[type=submit]');
    clearErrors($form);
    setBusy($button, true);
    try {
      const parent = $('#parentSelect').val();
      await postJson('/api/v1/hr/departments/', {
        name: String($form.find('[name=name]').val() || '').trim(),
        parent_id: parent ? Number(parent) : null
      });
      $form[0].reset();
      await loadDepartments();
    } catch (error) {
      showErrors($form, error);
    } finally {
      setBusy($button, false);
    }
  });

  $('#departments').on('click', '[data-rename]', async function onRename() {
    const department = departments.find((item) => item.id === Number($(this).data('rename')));
    const name = await promptDialog({ title: 'Переименовать подразделение', value: department.name });
    if (!name) {
      return;
    }
    try {
      await patchJson(`/api/v1/hr/departments/${department.id}/`, { name });
      await loadDepartments();
      loadEmployees();
    } catch (error) {
      toastError(error);
    }
  });

  $('#departments').on('click', '[data-remove]', async function onRemove() {
    const department = departments.find((item) => item.id === Number($(this).data('remove')));
    const confirmed = await confirmDialog({
      title: `Удалить «${department.name}»?`,
      message: 'Сотрудники подразделения останутся без подразделения.',
      confirmText: 'Удалить',
      danger: true
    });
    if (!confirmed) {
      return;
    }
    try {
      await deleteJson(`/api/v1/hr/departments/${department.id}/`);
      await loadDepartments();
      loadEmployees();
    } catch (error) {
      toastError(error);
    }
  });

  $('#employees').on('change', '[data-employee-field]', async function onEmployeeChange() {
    const $input = $(this);
    const field = $input.data('employee-field');
    const userId = $input.closest('tr').data('user');
    let value = $input.is(':checkbox') ? $input.prop('checked') : $input.val();
    if (field === 'department_id') {
      value = value ? Number(value) : null;
    }
    try {
      await patchJson(`/api/v1/hr/employees/${userId}/`, { [field]: value });
      toast('Сохранено.', 'success');
    } catch (error) {
      toastError(error);
      loadEmployees();
    }
  });

  $('#search').on('input', function onSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadEmployees, 300);
  });

  $('#departmentFilter').on('change', loadEmployees);

  loadDepartments().then(loadEmployees);
});
