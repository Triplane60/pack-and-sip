const API_BASE = '/api';
let PRODUCTS = [];

// Force browser to scroll to top on page reload
if ('scrollRestoration' in history) {
    history.scrollRestoration = 'manual';
}

window.addEventListener('beforeunload', () => {
    window.scrollTo(0, 0);
});

document.addEventListener('DOMContentLoaded', () => {
    window.scrollTo(0, 0);
});

function showCustomAlert(message) {
  document.getElementById('custom-alert-message').innerText = message;
  document.getElementById('custom-alert-modal').classList.add('is-open');
}
function closeCustomAlert() {
  document.getElementById('custom-alert-modal').classList.remove('is-open');
}

function formatPrice(value){

  return `₱${Number(value || 0).toFixed(2)}`;
}

async function fetchProducts(){
  const res = await fetch(`${API_BASE}/products`);
  const data = await res.json();
  PRODUCTS = Array.isArray(data) ? data : (data.products || []);
  renderCatalog();
}

function findProductById(id){
  return PRODUCTS.find(p => p.id === id);
}

function getProductImage(product){
  const label = product.type === 'cup' ? `${product.size} Cup` : product.type === 'lid' ? `${product.style} Lid` : `${product.name}`;
  const background = product.type === 'cup' ? 'e0e7ff' : product.type === 'lid' ? 'f1f5f9' : 'ecfdf5';
  const foreground = product.type === 'cup' ? '3730a3' : product.type === 'lid' ? '334155' : '047857';
  return `https://placehold.co/640x300/${background}/${foreground}?text=${encodeURIComponent(label)}`;
}

function renderCatalog(){
  const list = document.getElementById('productList');
  const microwavableList = document.getElementById('microwavableList');
  if(!list || !microwavableList) return;
  list.innerHTML = '';
  microwavableList.innerHTML = '';

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
              <span class="cardPrice text-2xl font-bold text-indigo-700">${formatPrice(product.price_per_box)}</span>
              <span class="cardPriceUnit text-xs text-slate-500"> / box</span>
            </div>
            <span class="text-xs text-slate-500">${stock} box(es)</span>
          </div>
        </div>
      </div>
      <div class="p-5 pt-0">
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="qtyBtn qtyMinus flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-slate-300 text-lg font-bold text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Decrease quantity for ${product.name}"
            ${stock === 0 ? 'disabled' : ''}
          >&minus;</button>
                    <input
            type="number"
            min="0"
            value="0"
            class="qtyInput w-full rounded-md border border-slate-300 px-2 py-1.5 text-center text-sm font-semibold text-slate-800"
            placeholder="0"
            aria-label="Quantity for ${product.name}"
            title="Quantity for ${product.name}"
            ${stock === 0 ? 'disabled' : ''}
          />

          <button
            type="button"
            class="qtyBtn qtyPlus flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-slate-300 text-lg font-bold text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Increase quantity for ${product.name}"
            ${stock === 0 ? 'disabled' : ''}
          >+</button>
        </div>
      </div>
    `;
    card.dataset.qtyId = product.id;
    const qtyInput = card.querySelector('.qtyInput');
    const qtyMinus = card.querySelector('.qtyMinus');
    const qtyPlus = card.querySelector('.qtyPlus');
    qtyMinus.addEventListener('click', () => {
      const current = parseInt(qtyInput.value || 0, 10) || 0;
      applyCatalogQty(product, current - 1);
    });
    qtyPlus.addEventListener('click', () => {
      const current = parseInt(qtyInput.value || 0, 10) || 0;
      applyCatalogQty(product, current + 1);
    });
    qtyInput.addEventListener('input', () => applyCatalogQty(product, qtyInput.value));
    (product.type === 'microwavable' ? microwavableList : list).appendChild(card);
  });
}

function resetConfigurator(){
  selectedCupId = null;
  selectedLidId = null;
  selectedMicrowavableId = null;
  Object.keys(qtys).forEach(id => delete qtys[id]);
  document.getElementById('cupBoxesInput').value = '0';
  document.getElementById('lidBoxesInput').value = '0';
  document.getElementById('microwavableBoxesInput').value = '0';
  updateConfiguratorActionState();
  syncCategoryTotals();
  document.getElementById('subtotal').innerText = '₱0.00';
  document.getElementById('shipping').innerText = '₱0.00';
  document.getElementById('total').innerText = '₱0.00';
  document.getElementById('cartCount').innerText = '0';
  document.getElementById('cartContent').innerHTML = '<p class="text-sm text-slate-600">No items in cart.</p>';
  refreshCatalogQuantityInputs();
  updateCheckoutTotals();
}

function updateConfiguratorActionState(){
  const viewCart = document.getElementById('viewCart');
  if(!viewCart) return;
  const hasItems = PRODUCTS.some(product => getQty(product) > 0);
  viewCart.disabled = !hasItems;
}

function applyCatalogQty(product, value){
  // Clamp the entered/edited quantity to the available stock: never below 0,
  // never above what's in stock. Applies independently per product card.
  const parsed = Math.max(0, Math.min(parseInt(value, 10) || 0, Number(product.stock_boxes || 0)));
  setQty(product, parsed);
  updateConfiguratorActionState();
  refreshCatalogQuantityInputs();
  syncCategoryTotals();
  calculate();
}

function refreshCatalogQuantityInputs(){
  // Mirror the Quick Configurator quantities back onto the matching catalog
  // card inputs AND update each card's dynamic price display so everything
  // stays in sync. Card price = unit price × quantity (total) when qty > 1;
  // otherwise the base unit price is shown.
  const cards = document.querySelectorAll('[data-qty-id]');
  cards.forEach(card => {
    const product = findProductById(card.dataset.qtyId);
    if(!product) return;

    const input = card.querySelector('.qtyInput');
    if(input) input.value = getQty(product);

    const priceEl = card.querySelector('.cardPrice');
    if(!priceEl) return;
    const unitEl = card.querySelector('.cardPriceUnit');
    const qty = getQty(product);
    const unitPrice = Number(product.price_per_box || 0);
    if(qty > 1){
      const lineTotal = Math.round(qty * unitPrice * 100) / 100;
      priceEl.textContent = formatPrice(lineTotal);
      if(unitEl) unitEl.textContent = ` / ${qty} boxes total`;
    }else{
      priceEl.textContent = formatPrice(unitPrice);
      if(unitEl) unitEl.textContent = ' / box';
    }
  });
}

function showToast(message) {
  let toast = document.getElementById('cart-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'cart-toast';
    document.body.appendChild(toast);
  }
  
  toast.textContent = message;
  toast.className = 'fixed z-[100] bg-slate-900 text-white px-6 py-3 rounded-full shadow-2xl transition-all duration-300 opacity-0 scale-95 font-semibold cart-toast-position';
  
  // Trigger animation
  requestAnimationFrame(() => {
    toast.classList.remove('opacity-0', 'scale-95');
    toast.classList.add('opacity-100', 'scale-100');
  });

  // Hide after 2.5 seconds
  setTimeout(() => {
    toast.classList.remove('opacity-100', 'scale-100');
    toast.classList.add('opacity-0', 'scale-95');
  }, 2500);
}




let selectedCupId = null;
let selectedLidId = null;
let selectedMicrowavableId = null;
// Per-product box quantities so every catalog card (12oz, 16oz, 22oz cups,
// lid styles, microwavable sizes) can be ordered independently.
const qtys = {};

// ---------------------------------------------------------------------------
// Quantity sync + price calculation
// ---------------------------------------------------------------------------

// 1. Item Category Summing:
//    Cup Boxes = Qty(12oz) + Qty(16oz) + Qty(22oz).
//    Lid Boxes = Qty(Strawless) + Qty(Dome) + Qty(Flat).
//    Microwavable Boxes = sum of all microwavable container card quantities.
//    Quantities are read from the per-card `qtys` map keyed by product id, so
//    every catalog card contributes independently via its own price per box.
function getQtyById(id){
  return Math.max(0, parseInt(qtys[id] || 0, 10) || 0);
}

function getCategoryTotals(){
  // Explicit per-SKU sums required by the spec. Any future/unknown SKUs of
  // the same type are folded in via the type fallback so totals never drift.
  let cupBoxes = getQtyById('cup-12oz') + getQtyById('cup-16oz') + getQtyById('cup-22oz');
  let lidBoxes = getQtyById('lid-strawless') + getQtyById('lid-dome') + getQtyById('lid-flat');
  let microwavableBoxes = 0;
  PRODUCTS.forEach(product => {
    const boxes = getQty(product);
    if(product.type === 'cup' && !['cup-12oz', 'cup-16oz', 'cup-22oz'].includes(product.id)) cupBoxes += boxes;
    else if(product.type === 'lid' && !['lid-strawless', 'lid-dome', 'lid-flat'].includes(product.id)) lidBoxes += boxes;
    else if(product.type === 'microwavable') microwavableBoxes += boxes;
  });
  return { cupBoxes, lidBoxes, microwavableBoxes };
}

// 2. Quick Configurator Sync:
//    Mirror the summed category totals onto the configurator inputs/readouts so
//    catalog card edits are reflected live in the Quick Configurator.
function syncCategoryTotals(){
  const totals = getCategoryTotals();
  const cupInput = document.getElementById('cupBoxesInput');
  const lidInput = document.getElementById('lidBoxesInput');
  const microInput = document.getElementById('microwavableBoxesInput');
  if(cupInput && document.activeElement !== cupInput) cupInput.value = String(totals.cupBoxes);
  if(lidInput && document.activeElement !== lidInput) lidInput.value = String(totals.lidBoxes);
  if(microInput && document.activeElement !== microInput) microInput.value = String(totals.microwavableBoxes);

  const cupBoxesEl = document.getElementById('config-cup-boxes');
  const lidBoxesEl = document.getElementById('config-lid-boxes');
  const microBoxesEl = document.getElementById('config-micro-boxes');
  if(cupBoxesEl) cupBoxesEl.textContent = String(totals.cupBoxes);
  if(lidBoxesEl) lidBoxesEl.textContent = String(totals.lidBoxes);
  if(microBoxesEl) microBoxesEl.textContent = String(totals.microwavableBoxes);
  return totals;
}

// Distribute a Quick Configurator category total back across that category's
// catalog cards. The typed value is split evenly (front-loaded remainder) and
// each share is clamped to that product's available stock. Remainders that do
// not fit are left unallocated and reported via the configurator input.
function distributeCategoryQty(type, total){
  const items = PRODUCTS.filter(p => p.type === type);
  if(items.length === 0) return;
  const wanted = Math.max(0, parseInt(total, 10) || 0);
  const perItem = Math.floor(wanted / items.length);
  let remainder = wanted - perItem * items.length;
  items.forEach(product => {
    const stock = Number(product.stock_boxes || 0);
    let share = perItem + (remainder > 0 ? 1 : 0);
    if(remainder > 0) remainder -= 1;
    share = Math.max(0, Math.min(share, stock));
    qtys[product.id] = share;
    if(product.type === 'cup') selectedCupId = product.id;
    else if(product.type === 'lid') selectedLidId = product.id;
    else selectedMicrowavableId = product.id;
  });
}

function productConfiguratorId(product){
  if(product.type === 'cup') return 'cupBoxesInput';
  if(product.type === 'lid') return 'lidBoxesInput';
  return 'microwavableBoxesInput';
}

function getQty(product){
  return Math.max(0, parseInt(qtys[product.id] || 0, 10) || 0);
}

function setQty(product, value){
  const parsed = Math.max(0, Math.min(parseInt(value, 10) || 0, Number(product.stock_boxes || 0)));
  qtys[product.id] = parsed;
  if(product.type === 'cup') selectedCupId = product.id;
  else if(product.type === 'lid') selectedLidId = product.id;
  else selectedMicrowavableId = product.id;
}

async function calculate(){
  // 3. Live Subtotal & Total Updates:
  //    Multiply every selected item's unit price by its box quantity, then
  //    update Subtotal / Shipping / Final Total in real-time on both the Quick
  //    Configurator and the Cart modal. Re-sync the summed category totals
  //    first so the configurator inputs/readouts match the catalog cards.
  syncCategoryTotals();

  // Aggregate every independently-ordered catalog item (12oz/16oz/22oz cups,
  // lid styles, microwavable containers) by its own price per box.
  let subtotal = 0;
  const items = [];
  PRODUCTS.forEach(product => {
    const boxes = getQty(product);
    if(boxes <= 0) return;
    const lineTotal = Math.round(boxes * Number(product.price_per_box || 0) * 100) / 100;
    subtotal += lineTotal;
    items.push({
      id: product.id,
      name: product.name,
      boxes,
      quantity_per_box: product.quantity_per_box,
      line_total: lineTotal
    });
  });
  subtotal = Math.round(subtotal * 100) / 100;

  // Flat base shipping fee when the cart is not empty.
  const shipping = subtotal > 0 ? 15 : 0;
  const total = Math.round((subtotal + shipping) * 100) / 100;

  updateSummary({
    subtotal,
    shipping,
    total,
    items
  });
}

function updateSummary(data){
  document.getElementById('subtotal').innerText = formatPrice(data.subtotal);
  document.getElementById('shipping').innerText = formatPrice(data.shipping);
  document.getElementById('total').innerText = formatPrice(data.total);
  const cartContent = document.getElementById('cartContent');
  if((data.items || []).length === 0){
    cartContent.innerHTML = `<p class="text-sm text-slate-600">No items in cart.</p>`;
    document.getElementById('cartCount').innerText = '0';
    updateCheckoutTotals();
    return;
  }
  document.getElementById('cartCount').innerText = data.items.reduce((s,i)=>s+i.boxes,0);
  cartContent.innerHTML = '';
  data.items.forEach(it => {
    const row = document.createElement('div');
    row.className = 'flex items-center justify-between py-2 border-b';
    const boxLabel = Number(it.boxes) === 1 ? 'box' : 'boxes';
    row.innerHTML = `<div><div class="font-medium">${it.name}</div><div class="text-sm text-slate-600">${it.boxes} ${boxLabel} - ${it.quantity_per_box} units/box</div></div><div class="text-right">${formatPrice(it.line_total)}</div>`;
    cartContent.appendChild(row);
  });
  const totals = document.createElement('div');
  totals.className = 'pt-3';
  totals.innerHTML = `<div class="flex items-center justify-between"><div class="text-sm">Subtotal</div><div class="font-medium">${formatPrice(data.subtotal)}</div></div><div class="flex items-center justify-between mt-2"><div class="text-sm">Shipping</div><div class="font-medium">${formatPrice(data.shipping)}</div></div><div class="flex items-center justify-between mt-3 text-lg font-bold text-indigo-700"><div>Total</div><div>${formatPrice(data.total)}</div></div>`;
  cartContent.appendChild(totals);
  updateCheckoutTotals();
}

function updateCheckoutTotals() {
  const totalStr = document.getElementById('total').innerText.replace(/[^0-9.]/g, '');
  const total = parseFloat(totalStr) || 0;
  const paymentType = document.getElementById('payment-type-select').value;
  
  let dueNow = total;
  let remaining = 0;
  
  if (paymentType === '50_percent') {
    dueNow = total * 0.5;
    remaining = total * 0.5;
    document.getElementById('remaining-balance-row').classList.remove('is-hidden-row');
    document.getElementById('remaining-balance-row').classList.add('is-block-row');
  } else {
    document.getElementById('remaining-balance-row').classList.remove('is-block-row');
    document.getElementById('remaining-balance-row').classList.add('is-hidden-row');
  }
  
  document.getElementById('due-now-amount').innerText = formatPrice(dueNow);
  document.getElementById('remaining-balance-amount').innerText = formatPrice(remaining);
}

// UI / drawer handlers
function openCart(){
  const panel = document.getElementById('drawerPanel');
  panel.classList.remove('drawer-closed-state');
  panel.classList.add('drawer-open-state');
  panel.setAttribute('aria-hidden','false');
  document.body.classList.add('drawer-open');
  updateBackToTopButton();
  updateCheckoutTotals();
}

function closeCart(){
  const panel = document.getElementById('drawerPanel');
  panel.classList.remove('drawer-open-state');
  panel.classList.add('drawer-closed-state');
  panel.setAttribute('aria-hidden','true');
  document.body.classList.remove('drawer-open');
  updateBackToTopButton();
}


// Event wiring
document.addEventListener('DOMContentLoaded', () => {
  resetConfigurator();
  fetchProducts();
  document.getElementById('cupBoxesInput').addEventListener('input', debounce(() => {
    // Quick Configurator Sync: distribute the typed Cup Boxes total across
    // 12oz/16oz/22oz cards, then refresh quantities + live totals.
    distributeCategoryQty('cup', document.getElementById('cupBoxesInput').value);
    updateConfiguratorActionState();
    refreshCatalogQuantityInputs();
    calculate();
  }, 300));
  document.getElementById('lidBoxesInput').addEventListener('input', debounce(() => {
    // Quick Configurator Sync: distribute the typed Lid Boxes total across
    // Strawless/Dome/Flat cards, then refresh quantities + live totals.
    distributeCategoryQty('lid', document.getElementById('lidBoxesInput').value);
    updateConfiguratorActionState();
    refreshCatalogQuantityInputs();
    calculate();
  }, 300));
  document.getElementById('microwavableBoxesInput').addEventListener('input', debounce(() => {
    // Quick Configurator Sync: distribute the typed Microwavable Boxes total
    // across all microwavable container cards, then refresh + live totals.
    distributeCategoryQty('microwavable', document.getElementById('microwavableBoxesInput').value);
    updateConfiguratorActionState();
    refreshCatalogQuantityInputs();
    calculate();
  }, 300));
  document.getElementById('customerPhone').addEventListener('input', function(){
    this.value = this.value.replace(/[^0-9]/g, '');
    if(this.value.length > 0 && !this.value.startsWith('09')){
      this.value = this.value.startsWith('9')
        ? `0${this.value}`
        : `09${this.value.replace(/^0+/, '')}`;
    }
    this.value = this.value.slice(0, 11);
  });
  document.getElementById('clearSelection').addEventListener('click', resetConfigurator);
  document.getElementById('viewCart').addEventListener('click', openCart);
  document.getElementById('cartBtn').addEventListener('click', openCart);
  document.getElementById('closeCart').addEventListener('click', closeCart);
  const checkoutForm = document.getElementById('checkoutForm');
  if(checkoutForm){
    checkoutForm.addEventListener('submit', (e) => {
      e.preventDefault();
      openConfirmationModal();
    });
  }
  document.getElementById('addMoreItemsBtn').addEventListener('click', closeConfirmationModal);
  document.getElementById('confirmOrderBtn').addEventListener('click', submitOrder);
  document.getElementById('closeModalBtn').addEventListener('click', closeOrderPendingModal);
  setupAuthModal();
  setupAboutModal();
  setupSecretAdminAccess();
});

// Auth modal handlers
let currentUser = null;

function setupAuthModal(){
  const authModal = document.getElementById('authModal');
  const authBtn = document.getElementById('authBtn');
  const closeAuth = document.getElementById('closeAuth');
  const tabLogin = document.getElementById('tabLogin');
  const tabRegister = document.getElementById('tabRegister');
  const loginForm = document.getElementById('loginForm');
  const registerForm = document.getElementById('registerForm');

    const openAuth = () => {
    authModal.classList.remove('hidden');
    authModal.classList.add('flex');
    document.body.classList.add('modal-open');
  };

  const closeAuthModal = () => {
    authModal.classList.add('hidden');
    authModal.classList.remove('flex');
    document.body.classList.remove('modal-open');
  };


  authBtn.addEventListener('click', openAuth);
  closeAuth.addEventListener('click', closeAuthModal);

  tabLogin.addEventListener('click', () => {
    tabLogin.classList.add('border-indigo-600', 'text-indigo-600');
    tabLogin.classList.remove('border-transparent', 'text-slate-500');
    tabRegister.classList.remove('border-indigo-600', 'text-indigo-600');
    tabRegister.classList.add('border-transparent', 'text-slate-500');
    loginForm.classList.remove('hidden');
    registerForm.classList.add('hidden');
  });

  tabRegister.addEventListener('click', () => {
    tabRegister.classList.add('border-indigo-600', 'text-indigo-600');
    tabRegister.classList.remove('border-transparent', 'text-slate-500');
    tabLogin.classList.remove('border-indigo-600', 'text-indigo-600');
    tabLogin.classList.add('border-transparent', 'text-slate-500');
    registerForm.classList.remove('hidden');
    loginForm.classList.add('hidden');
  });

  loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(loginForm);
    const data = Object.fromEntries(formData.entries());

    try {
      const res = await fetch(`${API_BASE}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
        credentials: 'include'
      });

      const result = await res.json();
            if (res.ok) {
        currentUser = result.user;
        updateAuthUI();
        closeAuthModal();
        fillCustomerData();
      } else {
        showCustomAlert(result.error);
      }
    } catch (err) {
      showCustomAlert('Login failed');
    }
  });

  registerForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(registerForm);
    const data = Object.fromEntries(formData.entries());

    try {
      const res = await fetch(`${API_BASE}/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
        credentials: 'include'
      });
      const result = await res.json();
      if (res.ok) {
        currentUser = result.user;
        updateAuthUI();
        closeAuthModal();
        fillCustomerData();
      } else {
        showCustomAlert(result.error);
      }
    } catch (err) {
      showCustomAlert('Registration failed');
    }
  });


  document.getElementById('logoutBtn').addEventListener('click', () => {
    currentUser = null;
    updateAuthUI();
  });

    // Check if already logged in
  fetch(`${API_BASE}/me`, { credentials: 'include' })
    .then(res => res.json())

    .then(data => {
      if (data.user) {
        currentUser = data.user;
        updateAuthUI();
        fillCustomerData();
      }
    }).catch(() => {});
}

function updateAuthUI(){
  const authBtn = document.getElementById('authBtn');
  const logoutBtn = document.getElementById('logoutBtn');
  if (currentUser) {
    authBtn.textContent = currentUser.full_name;
    authBtn.disabled = true;
    logoutBtn.classList.remove('hidden');
  } else {
    authBtn.textContent = 'Login / Register';
    authBtn.disabled = false;
    logoutBtn.classList.add('hidden');
  }
}

function fillCustomerData(){
  if (currentUser) {
    const nameField = document.getElementById('customerName');
    const emailField = document.getElementById('customerEmail');
    const addressField = document.getElementById('customerAddress');
    const phoneField = document.getElementById('customerPhone');

    if (nameField) nameField.value = currentUser.full_name || '';
    if (emailField) {
      emailField.value = currentUser.email || '';
      emailField.readOnly = true;
      emailField.classList.add('bg-slate-50', 'text-slate-500', 'cursor-not-allowed');
    }
    if (addressField) addressField.value = currentUser.shipping_address || '';
    if (phoneField) phoneField.value = currentUser.phone || '';
  }
}



function debounce(fn, wait){
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(()=>fn(...args), wait); };
}

function scrollToTop(event){
  if(event) event.preventDefault();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function updateBackToTopButton(){
  const button = document.getElementById('backToTopBtn');
  if(!button) return;
  const drawerOpen = document.body.classList.contains('drawer-open');
  button.classList.toggle('hidden', drawerOpen || window.scrollY <= 300);
}

window.addEventListener('scroll', updateBackToTopButton);

function closeOrderPendingModal(){
  const modal = document.getElementById('orderPendingModal');
  modal.classList.add('opacity-0');
  setTimeout(() => {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  }, 300);
  closeCart();
  resetConfigurator();
  document.getElementById('customerName').value = '';
  document.getElementById('customerEmail').value = '';
  document.getElementById('customerAddress').value = '';
  document.getElementById('customerPhone').value = '';
}

function showOrderPendingModal(email){
  document.getElementById('modalEmail').textContent = email;
  const modal = document.getElementById('orderPendingModal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  requestAnimationFrame(() => modal.classList.remove('opacity-0'));
}

function closeConfirmationModal(){
  const modal = document.getElementById('confirmOrderModal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
  document.body.classList.remove('modal-open');
}


function resetCheckoutState(){
  closeConfirmationModal();
  closeCart();
  resetConfigurator();
  document.getElementById('customerName').value = '';
  document.getElementById('customerEmail').value = '';
  document.getElementById('customerAddress').value = '';
  document.getElementById('customerPhone').value = '';
}


function validateCheckoutFields(){
  const name = document.getElementById('customerName').value.trim();
  const email = document.getElementById('customerEmail').value.trim();
  const address = document.getElementById('customerAddress').value.trim();
  const phone = document.getElementById('customerPhone').value.trim();

  if(!name || !email || !address || !phone){
    showCustomAlert('Please enter your name, email, address, and phone number.');
    return false;
  }

  if(!/^09\d{9}$/.test(phone)){
    showCustomAlert('Please enter a valid Philippine mobile number in the format 09123456789.');
    return false;
  }

  return true;
}


function populateCheckoutHiddenFields(){
  const setHidden = (id, value) => {
    const el = document.getElementById(id);
    if(el) el.value = (value === undefined || value === null) ? '' : value;
  };

  // Aggregate the independently-quantified catalog products into the single
  // product-per-category fields the checkout endpoint expects. For each type,
  // use the product with the highest quantity as the representative variation
  // and sum its category's boxes so nothing is silently dropped from the total.
  const itemsByType = { cup: [], lid: [], microwavable: [] };
  PRODUCTS.forEach(product => {
    const boxes = getQty(product);
    if(boxes <= 0) return;
    itemsByType[product.type] = itemsByType[product.type] || [];
    itemsByType[product.type].push({ product, boxes });
  });

  const cupItems = itemsByType.cup.sort((a,b) => b.boxes - a.boxes);
  const lidItems = itemsByType.lid.sort((a,b) => b.boxes - a.boxes);
  const microItems = itemsByType.microwavable.sort((a,b) => b.boxes - a.boxes);

  const cup = cupItems[0] || {};
  const lid = lidItems[0] || {};
  const micro = microItems[0] || {};
  const cupBoxes = cupItems.reduce((s, i) => s + i.boxes, 0);
  const lidBoxes = lidItems.reduce((s, i) => s + i.boxes, 0);
  const microBoxes = microItems.reduce((s, i) => s + i.boxes, 0);

  const subtotal = parseFloat(document.getElementById('subtotal').innerText.replace(/[^0-9.]/g, '') || 0);
  const shipping = parseFloat(document.getElementById('shipping').innerText.replace(/[^0-9.]/g, '') || 0);
  const total = parseFloat(document.getElementById('total').innerText.replace(/[^0-9.]/g, '') || 0);
  const paymentType = document.getElementById('payment-type-select').value;
  const dueNow = paymentType === '50_percent' ? Math.round(total * 0.5 * 100) / 100 : total;
  const remaining = paymentType === '50_percent' ? Math.round(total * 0.5 * 100) / 100 : 0;

  setHidden('checkoutCupId', cup.product ? cup.product.id : '');
  setHidden('checkoutCupSize', cup.product?.size || '');
  setHidden('checkoutCupBoxes', cupBoxes);
  setHidden('checkoutLidId', lid.product ? lid.product.id : '');
  setHidden('checkoutLidStyle', lid.product?.style || '');
  setHidden('checkoutLidBoxes', lidBoxes);
  setHidden('checkoutMicrowavableId', micro.product ? micro.product.id : '');
  setHidden('checkoutMicrowavableSize', micro.product?.size || '');
  setHidden('checkoutMicrowavableBoxes', microBoxes);
  setHidden('checkoutSubtotal', Math.round(subtotal * 100) / 100);
  setHidden('checkoutShipping', Math.round(shipping * 100) / 100);
  setHidden('checkoutTotal', Math.round(total * 100) / 100);
  setHidden('checkoutDueNow', dueNow);
  setHidden('checkoutRemainingBalance', remaining);
}

async function openConfirmationModal(){
  if(!validateCheckoutFields()) return;

  await calculate();
  populateCheckoutHiddenFields();
  document.body.classList.add('modal-open');
  const items = document.getElementById('confirmOrderItems');

  items.replaceChildren();
  const selectedItems = [];
  PRODUCTS.forEach(product => {
    const boxes = getQty(product);
    if(boxes <= 0) return;
    const label = product.type === 'cup' ? `Cups: ${product.size}` : product.type === 'lid' ? `Lids: ${product.style} Lid` : `Microwavable: ${product.size}`;
    selectedItems.push(`${label} - ${boxes} ${boxes === 1 ? 'box' : 'boxes'}`);
  });

  if(selectedItems.length === 0){
    items.innerHTML = '<p class="text-slate-500">No items selected.</p>';
  }else{
    selectedItems.forEach(item => {
      const line = document.createElement('div');
      line.textContent = item;
      items.appendChild(line);
    });
  }

  document.getElementById('confirmOrderTotal').textContent = document.getElementById('total').textContent;

  const totalAmount = Number(document.getElementById('total').textContent.replace(/[^0-9.]/g, '') || 0);
  const paymentType = document.getElementById('payment-type-select').value;
  const fullRow = document.getElementById('confirmOrderFullRow');
  const downpaymentRow = document.getElementById('confirmOrderDownpaymentRow');
  const paymentNote = document.getElementById('confirmOrderPaymentNote');

  if (paymentType === 'full') {
    // 100% Full Payment: show the full total as the required payment.
    fullRow.classList.remove('is-hidden-row');
    fullRow.classList.add('is-flex-row');
    downpaymentRow.classList.remove('is-flex-row');
    downpaymentRow.classList.add('is-hidden-row');
    document.getElementById('confirmOrderRequiredPayment').textContent = formatPrice(totalAmount);
    paymentNote.textContent = 'Full payment required via GCash/Maya.';
  } else {
    // 50% Downpayment: show half of the total and the balance-on-delivery note.
    fullRow.classList.remove('is-flex-row');
    fullRow.classList.add('is-hidden-row');
    downpaymentRow.classList.remove('is-hidden-row');
    downpaymentRow.classList.add('is-flex-row');
    const confirmDownpayment = Math.round(totalAmount * 0.5 * 100) / 100;
    document.getElementById('confirmOrderDownpayment').textContent = formatPrice(confirmDownpayment);
    paymentNote.textContent = 'A 50% downpayment is required via GCash/Maya to process your order. The remaining balance will be paid upon Lalamove delivery.';
  }

  const modal = document.getElementById('confirmOrderModal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

async function submitOrder(){
  if(!validateCheckoutFields()) return;
  const email = document.getElementById('customerEmail').value.trim();

  try{
    // Recalculate the totals and mirror the selected items/quantities/totals
    // into the hidden fields of #checkoutForm so the POSTed payload is complete.
    await calculate();
    populateCheckoutHiddenFields();

    const formData = new FormData(document.getElementById('checkoutForm'));

    // Clear the local cart and close checkout before waiting for the network request.
    resetCheckoutState();
    const res = await fetch('/checkout', {
      method: 'POST',
      body: formData,
      credentials: 'include'
    });
    const data = await res.json();
    if(!res.ok){
      showCustomAlert(data.error || 'Failed to place order');
      return;
    }
    showOrderPendingModal(email);
    // Refresh product list to reflect updated stock
    await fetchProducts();
  }catch(err){
    showCustomAlert('Network error placing order');
  }
}



function openAbout(){
  const modal = document.getElementById('aboutModal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  document.body.classList.add('modal-open');
}

function closeAbout(){
  const modal = document.getElementById('aboutModal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
  document.body.classList.remove('modal-open');
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
