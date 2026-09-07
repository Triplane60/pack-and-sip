const API_BASE = 'http://127.0.0.1:5000/api';
let PRODUCTS = [];

function formatPrice(value){
  return `₱${Number(value || 0).toFixed(2)}`;
}

async function fetchProducts(){
  const res = await fetch(`${API_BASE}/products`);
  const data = await res.json();
  PRODUCTS = Array.isArray(data) ? data : (data.products || []);
  renderProductOptions();
  renderCatalog();
}

function findProductById(id){
  return PRODUCTS.find(p => p.id === id);
}

function renderProductOptions(){
  const cupOptions = document.getElementById('cupOptions');
  const lidSelect = document.getElementById('lidSelect');
  cupOptions.innerHTML = '';
  lidSelect.innerHTML = '<option value="" disabled selected>Select lid style...</option>';

  const cups = PRODUCTS.filter(p => p.type === 'cup');
  cups.forEach((c, idx) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'border rounded-md p-2 text-sm';
    btn.innerText = c.size;
    btn.dataset.id = c.id;
    btn.addEventListener('click', () => {
      selectCup(c.id);
    });
    cupOptions.appendChild(btn);
  });

  if(selectedCupId){
    updateCupPreview(findProductById(selectedCupId));
  }else{
    updateCupPreview(null);
  }

  const lids = PRODUCTS.filter(p => p.type === 'lid');
  lids.forEach(l => {
    const opt = document.createElement('option');
    opt.value = l.id;
    opt.text = l.style + ' — ' + formatPrice(l.price_per_box) + '/box';
    lidSelect.appendChild(opt);
  });
  if(selectedLidId){
    lidSelect.value = selectedLidId;
    updateLidPreview(findProductById(selectedLidId));
  }else{
    updateLidPreview(null);
  }
  calculate();
}

function getProductImage(product){
  const label = product.type === 'cup' ? `${product.size} Cup` : `${product.style} Lid`;
  const background = product.type === 'cup' ? 'e0e7ff' : 'f1f5f9';
  const foreground = product.type === 'cup' ? '3730a3' : '334155';
  return `https://placehold.co/640x300/${background}/${foreground}?text=${encodeURIComponent(label)}`;
}

function renderCatalog(){
  const list = document.getElementById('productList');
  if(!list) return;
  list.innerHTML = '';

  PRODUCTS.forEach(product => {
    const card = document.createElement('article');
    const stock = Number(product.stock_boxes || 0);
    const stockLabel = stock > 0 ? 'In Stock' : 'Out of Stock';
    const stockClasses = stock > 0 ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600';
    card.className = 'flex flex-col justify-between overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm';
    card.innerHTML = `
      <div>
        <div class="flex items-start justify-between gap-3 p-5 pb-3">
          <h3 class="font-semibold text-slate-900">${product.name}</h3>
          <span class="shrink-0 rounded-full px-2 py-1 text-xs font-semibold ${stockClasses}">${stockLabel}</span>
        </div>
        <img src="${getProductImage(product)}" alt="${product.name} preview" class="h-40 w-full object-cover" />
        <div class="p-5 pt-4">
          <p class="text-sm text-slate-600">${product.description}</p>
          <div class="mt-4 flex items-end justify-between gap-3">
            <div>
              <span class="text-2xl font-bold text-indigo-700">${formatPrice(product.price_per_box)}</span>
              <span class="text-xs text-slate-500"> / box</span>
            </div>
            <span class="text-xs text-slate-500">${stock} box(es)</span>
          </div>
        </div>
      </div>
      <div class="p-5 pt-0">
        <button type="button" class="quickAdd w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300" ${stock === 0 ? 'disabled' : ''}>Quick Add</button>
      </div>
    `;
    card.querySelector('.quickAdd').addEventListener('click', () => quickAdd(product));
    list.appendChild(card);
  });
}

function quickAdd(product){
  const stock = Number(product.stock_boxes || 0);
  if(stock <= 0) return;

  if(product.type === 'cup'){
    selectCup(product.id);
    const input = document.getElementById('cupBoxes');
    input.value = Math.min(parseInt(input.value || 0, 10) + 1, stock);
  }else{
    const lidSelect = document.getElementById('lidSelect');
    lidSelect.value = product.id;
    selectedLidId = product.id;
    updateLidPreview(product);
    const input = document.getElementById('lidBoxes');
    input.value = Math.min(parseInt(input.value || 0, 10) + 1, stock);
  }
  calculate();
  openCart();
}

let selectedCupId = null;
let selectedLidId = null;
function selectCup(id){
  selectedCupId = id;
  updateCupPreview(findProductById(id));
  document.querySelectorAll('#cupOptions button').forEach(b => b.classList.remove('bg-indigo-50','ring'));
  const b = document.querySelector(`#cupOptions button[data-id='${id}']`);
  if(b){ b.classList.add('bg-indigo-50'); }
  calculate();
}

function updateCupPreview(product){
  const image = document.getElementById('cupPreview');
  if(!product){
    image.src = 'https://placehold.co/640x300/e0e7ff/3730a3?text=Select+a+cup+size';
    image.alt = 'Select a cup size to preview';
    return;
  }
  image.src = `https://placehold.co/640x300/e0e7ff/3730a3?text=${encodeURIComponent(product.size + ' Cup')}`;
  image.alt = `${product.size} cup product preview`;
}

function updateLidPreview(product){
  const image = document.getElementById('lidPreview');
  if(!product){
    image.src = 'https://placehold.co/640x300/f1f5f9/334155?text=Select+a+lid+style';
    image.alt = 'Select a lid style to preview';
    return;
  }
  image.src = `https://placehold.co/640x300/f1f5f9/334155?text=${encodeURIComponent(product.style + ' Lid')}`;
  image.alt = `${product.style} lid product preview`;
}

async function calculate(){
  const cupBoxes = Math.max(0, parseInt(document.getElementById('cupBoxes').value || 0, 10));
  const lidId = selectedLidId;
  const lidBoxes = Math.max(0, parseInt(document.getElementById('lidBoxes').value || 0, 10));

  const body = { cup_id: selectedCupId, cup_boxes: cupBoxes, lid_id: lidId, lid_boxes: lidBoxes };
  const res = await fetch(`${API_BASE}/cart/calculate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const data = await res.json();
  updateSummary(data);
}

function updateSummary(data){
  document.getElementById('subtotal').innerText = formatPrice(data.subtotal);
  document.getElementById('shipping').innerText = formatPrice(data.shipping);
  document.getElementById('total').innerText = formatPrice(data.total);
  const cartContent = document.getElementById('cartContent');
  if((data.items || []).length === 0){
    cartContent.innerHTML = `<p class="text-sm text-slate-600">No items in cart.</p>`;
    document.getElementById('cartCount').innerText = '0';
    return;
  }
  document.getElementById('cartCount').innerText = data.items.reduce((s,i)=>s+i.boxes,0);
  cartContent.innerHTML = '';
  data.items.forEach(it => {
    const row = document.createElement('div');
    row.className = 'flex items-center justify-between py-2 border-b';
    row.innerHTML = `<div><div class="font-medium">${it.name}</div><div class="text-sm text-slate-600">${it.boxes} box(es) • ${it.quantity_per_box} units/box</div></div><div class="text-right">${formatPrice(it.line_total)}</div>`;
    cartContent.appendChild(row);
  });
  const totals = document.createElement('div');
  totals.className = 'pt-3';
  totals.innerHTML = `<div class="flex items-center justify-between"><div class="text-sm">Subtotal</div><div class="font-medium">${formatPrice(data.subtotal)}</div></div><div class="flex items-center justify-between mt-2"><div class="text-sm">Shipping</div><div class="font-medium">${formatPrice(data.shipping)}</div></div><div class="flex items-center justify-between mt-3 text-lg font-bold text-indigo-700"><div>Total</div><div>${formatPrice(data.total)}</div></div>`;
  cartContent.appendChild(totals);
}

// UI / drawer handlers
function openCart(){
  const panel = document.getElementById('drawerPanel');
  panel.style.transform = 'translateX(0)';
  panel.setAttribute('aria-hidden','false');
}
function closeCart(){
  const panel = document.getElementById('drawerPanel');
  panel.style.transform = 'translateX(100%)';
  panel.setAttribute('aria-hidden','true');
}

// Event wiring
document.addEventListener('DOMContentLoaded', () => {
  fetchProducts();
  document.getElementById('cupBoxes').addEventListener('input', debounce(calculate, 300));
  document.getElementById('lidBoxes').addEventListener('input', debounce(calculate, 300));
  document.getElementById('customerPhone').addEventListener('input', function(){
    this.value = this.value.replace(/[^0-9]/g, '');
    if(this.value.length > 0 && !this.value.startsWith('09')){
      this.value = this.value.startsWith('9')
        ? `0${this.value}`
        : `09${this.value.replace(/^0+/, '')}`;
    }
    this.value = this.value.slice(0, 11);
  });
  document.getElementById('lidSelect').addEventListener('change', event => {
    selectedLidId = event.target.value || null;
    updateLidPreview(findProductById(selectedLidId));
    calculate();
  });
  document.getElementById('viewCart').addEventListener('click', openCart);
  document.getElementById('cartBtn').addEventListener('click', openCart);
  document.getElementById('closeCart').addEventListener('click', closeCart);
  const checkoutBtn = document.getElementById('checkoutBtn');
  if(checkoutBtn) checkoutBtn.addEventListener('click', submitOrder);
  setupAboutModal();
  setupSecretAdminAccess();
});

function debounce(fn, wait){
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(()=>fn(...args), wait); };
}

async function submitOrder(){
  const name = document.getElementById('customerName').value.trim();
  const email = document.getElementById('customerEmail').value.trim();
  const address = document.getElementById('customerAddress').value.trim();
  const phone = document.getElementById('customerPhone').value.trim();
  const cupBoxes = Math.max(0, parseInt(document.getElementById('cupBoxes').value || 0, 10));
  const lidId = selectedLidId;
  const lidBoxes = Math.max(0, parseInt(document.getElementById('lidBoxes').value || 0, 10));
  const paymentMethod = document.querySelector('input[name="paymentMethod"]:checked')?.value || '';

  if(!name || !email || !address || !phone || !paymentMethod){
    alert('Please enter your name, email, address, phone number, and payment method.');
    return;
  }

  if(!/^09\d{9}$/.test(phone)){
    alert('Please enter a valid Philippine mobile number in the format 09123456789.');
    return;
  }

  const payload = {
    // Keep the existing checkout contract while also exposing the requested field names.
    name, address, phone, email,
    fullName: name,
    shippingAddress: address,
    phoneNumber: phone,
    paymentMethod,
    cup_id: selectedCupId,
    cup_boxes: cupBoxes,
    lid_id: lidId,
    lid_boxes: lidBoxes,
    payment_method: paymentMethod
  };

  try{
    const res = await fetch(`${API_BASE}/checkout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if(!res.ok){
      alert(data.error || 'Failed to place order');
      return;
    }
    alert(`Order successful — ID: ${data.order_id} — Total: ${formatPrice(data.total)}`);
    // Refresh product list to reflect updated stock
    await fetchProducts();
    // Reset inputs and close drawer
    document.getElementById('customerName').value = '';
    document.getElementById('customerEmail').value = '';
    document.getElementById('customerAddress').value = '';
    document.getElementById('customerPhone').value = '';
    document.getElementById('cupBoxes').value = 0;
    document.getElementById('lidBoxes').value = 0;
    document.querySelector('input[name="paymentMethod"][value="GCash"]').checked = true;
    updateSummary({ items: [], subtotal: 0, shipping: 0, total: 0 });
    closeCart();
  }catch(err){
    alert('Network error placing order');
  }
}

function openAbout(){
  const modal = document.getElementById('aboutModal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

function closeAbout(){
  const modal = document.getElementById('aboutModal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

function setupAboutModal(){
  const aboutLink = document.getElementById('aboutLink');
  const closeButton = document.getElementById('closeAbout');
  const modal = document.getElementById('aboutModal');
  aboutLink.addEventListener('click', event => {
    event.preventDefault();
    openAbout();
  });
  closeButton.addEventListener('click', closeAbout);
  modal.addEventListener('click', event => {
    if(event.target === modal) closeAbout();
  });
  document.addEventListener('keydown', event => {
    if(event.key === 'Escape') closeAbout();
  });
}

function setupSecretAdminAccess(){
  const siteLogo = document.getElementById('siteLogo');
  const openAdmin = () => { window.location.href = 'manage-orders-ps.html'; };

  document.addEventListener('keydown', event => {
    if(event.ctrlKey && event.shiftKey && event.key.toLowerCase() === 'a'){
      event.preventDefault();
      openAdmin();
    }
  });

  if(siteLogo) siteLogo.addEventListener('dblclick', openAdmin);
}
