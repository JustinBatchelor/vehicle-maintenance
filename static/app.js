document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.videos-details').forEach(details => {
    details.addEventListener('toggle', () => { if (details.open && window.htmx) htmx.trigger(details.querySelector('.video-loader'), 'tutorials'); });
  });
  const filter = document.getElementById('status-filter');
  if (filter) filter.addEventListener('change', () => {
    let shown = 0;
    document.querySelectorAll('.tasks .task').forEach(task => {
      const match = filter.value === 'all' || (filter.value === 'attention' ? ['overdue','due','due-soon'].includes(task.dataset.status) : filter.value === 'upcoming' ? ['upcoming','due-soon'].includes(task.dataset.status) : task.dataset.status === filter.value);
      task.hidden = !match; if (match) shown++;
    });
    document.getElementById('no-filter-results').hidden = shown > 0;
  });
  const catalogNode = document.getElementById('vehicle-catalog');
  if (!catalogNode) return;
  const catalog = JSON.parse(catalogNode.textContent);
  const configSelect = document.getElementById('id_configuration');
  const fields = ['make','model','year','trim'];
  const selectors = fields.map(f => document.getElementById('select-' + f));
  const initial = catalog.find(c => String(c.id) === configSelect.value);
  document.getElementById('vehicle-selectors').hidden = false;
  const fill = (select, values, placeholder, selected) => {
    select.replaceChildren(new Option(placeholder, ''));
    [...new Set(values)].forEach(v => select.add(new Option(String(v), String(v))));
    if (selected != null) select.value = String(selected);
    if (!select.value && values.length === 1) select.value = String(values[0]);
  };
  const update = (start=0) => {
    let subset = catalog;
    fields.forEach((field,index) => {
      if (index >= start) fill(selectors[index], [...new Set(subset.map(c=>c[field]))], 'Choose '+field, start===0 && initial ? initial[field] : selectors[index].value);
      subset = subset.filter(c => String(c[field]) === selectors[index].value);
    });
    const previous = configSelect.value;
    configSelect.replaceChildren(new Option('Confirm engine, transmission and drivetrain', ''));
    subset.forEach(c => configSelect.add(new Option(`${c.engine} · ${c.transmission} · ${c.drivetrain}`, String(c.id))));
    configSelect.value = subset.some(c => String(c.id) === previous) ? previous : (subset.length===1 ? String(subset[0].id) : '');
    renderConditions();
  };
  const renderConditions = () => {
    const c = catalog.find(c => String(c.id) === configSelect.value);
    ['conditions','equipment'].forEach(field => {
      const container = document.getElementById('id_'+field);
      if (!container) return;
      const checked = new Set([...container.querySelectorAll('input:checked')].map(i=>i.value));
      const choices = c ? c[field === 'conditions' ? 'condition_options' : 'equipment_options'] : {};
      container.replaceChildren();
      Object.entries(choices).forEach(([value,text], index) => {
        const div = document.createElement('div'), label = document.createElement('label'), input = document.createElement('input');
        input.type='checkbox'; input.name=field; input.value=value; input.id=`id_${field}_${index}`; input.checked=checked.has(value);
        label.htmlFor=input.id; label.append(input, document.createTextNode(text)); div.append(label); container.append(div);
      });
      if (!Object.keys(choices).length) { const p=document.createElement('p'); p.className='helptext'; p.textContent=c?'No additional equipment to confirm.':'Choose a vehicle configuration first.'; container.append(p); }
    });
  };
  selectors.forEach((s,i) => s.addEventListener('change',()=>{ selectors.slice(i+1).forEach(x=>x.value=''); update(i+1); }));
  configSelect.addEventListener('change',renderConditions); update();
});
