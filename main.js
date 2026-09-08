const API_BASE = 'http://127.0.0.1:5000/api';
const MICROWAVABLE_BASE_PRICE = 1500;
let PRODUCTS = [];

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
    (product.type === 'microwavable' ? microwavableList : list).appendChild(card);
  });
}

function resetConfigurator(){
  selectedCupId = null;
  selectedLidId = null;
  selectedMicrowavableId = null;
  document.getElementById('cupBoxesInput').value = '0';
  document.getElementById('lidBoxesInput').value = '0';
  document.getElementById('microwavableBoxesInput').value = '0';
  updateConfiguratorActionState();
  document.getElementById('subtotal').innerText = '₱0.00';
  document.getElementById('shipping').innerText = '₱0.00';
  document.getElementById('total').innerText = '₱0.00';
  document.getElementById('cartCount').innerText = '0';
  document.getElementById('cartContent').innerHTML = '<p class="text-sm text-slate-600">No items in cart.</p>';
}

function updateConfiguratorActionState(){
  const viewCart = document.getElementById('viewCart');
  const microwavableBoxes = Number(document.getElementById('microwavableBoxesInput').value || 0);
  if(viewCart) viewCart.disabled = !selectedCupId && !selectedLidId && microwavableBoxes <= 0;
}

function quickAdd(product){
  const stock = Number(product.stock_boxes || 0);
  if(stock <= 0) return;

  if(product.type === 'cup'){
    selectedCupId = product.id;
    const input = document.getElementById('cupBoxesInput');
    input.value = Math.min(parseInt(input.value || 0, 10) + 1, stock);
  }else if(product.type === 'lid'){
    selectedLidId = product.id;
    const input = document.getElementById('lidBoxesInput');
    input.value = Math.min(parseInt(input.value || 0, 10) + 1, stock);
    updateConfiguratorActionState();
  }else{
    selectedMicrowavableId = product.id;
    const input = document.getElementById('microwavableBoxesInput');
    input.value = Math.min(parseInt(input.value || 0, 10) + 1, stock);
  }
  updateConfiguratorActionState();
  calculate();
  openCart();
}

let selectedCupId = null;
let selectedLidId = null;
let selectedMicrowavableId = null;

async function calculate(){
  const cupBoxes = Math.max(0, parseInt(document.getElementById('cupBoxesInput').value || 0, 10));
  const lidId = selectedLidId;
  const lidBoxes = Math.max(0, parseInt(document.getElementById('lidBoxesInput').value || 0, 10));
  const microwavableBoxes = Math.max(0, parseInt(document.getElementById('microwavableBoxesInput').value || 0, 10));

  const body = { cup_id: selectedCupId, cup_boxes: cupBoxes, lid_id: lidId, lid_boxes: lidBoxes };
  const res = await fetch(`${API_BASE}/cart/calculate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const data = await res.json();
  const microwavableSubtotal = microwavableBoxes * MICROWAVABLE_BASE_PRICE;
  const subtotal = Number(data.subtotal || 0) + microwavableSubtotal;
  const shipping = Number(data.shipping || 0) || (microwavableSubtotal > 0 ? 15 : 0);
  data.subtotal = Math.round(subtotal * 100) / 100;
  data.shipping = shipping;
  data.total = Math.round((subtotal + shipping) * 100) / 100;
  data.items = data.items || [];
  if(microwavableBoxes > 0){
    data.items.push({
      name: 'Microwavable containers',
      boxes: microwavableBoxes,
      quantity_per_box: 100,
      line_total: microwavableSubtotal
    });
  }
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
    const boxLabel = Number(it.boxes) === 1 ? 'box' : 'boxes';
    row.innerHTML = `<div><div class="font-medium">${it.name}</div><div class="text-sm text-slate-600">${it.boxes} ${boxLabel} - ${it.quantity_per_box} units/box</div></div><div class="text-right">${formatPrice(it.line_total)}</div>`;
    cartContent.appendChild(row);
  });
  const totals = document.createElement('div');
  totals.className = 'pt-3';
  const downpayment = Number(data.downpayment_amount ?? (Number(data.total || 0) * 0.5));
  totals.innerHTML = `<div class="flex items-center justify-between"><div class="text-sm">Subtotal</div><div class="font-medium">${formatPrice(data.subtotal)}</div></div><div class="flex items-center justify-between mt-2"><div class="text-sm">Shipping</div><div class="font-medium">${formatPrice(data.shipping)}</div></div><div class="flex items-center justify-between mt-3 text-lg font-bold text-indigo-700"><div>Total</div><div>${formatPrice(data.total)}</div></div><div class="flex items-center justify-between mt-2 text-sm font-semibold text-amber-700"><div>Required 50% Downpayment</div><div>${formatPrice(downpayment)}</div></div>`;
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
  resetConfigurator();
  fetchProducts();
  document.getElementById('cupBoxesInput').addEventListener('input', debounce(calculate, 300));
  document.getElementById('lidBoxesInput').addEventListener('input', debounce(calculate, 300));
  document.getElementById('microwavableBoxesInput').addEventListener('input', debounce(() => {
    updateConfiguratorActionState();
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
  const checkoutBtn = document.getElementById('checkoutBtn');
  if(checkoutBtn) checkoutBtn.addEventListener('click', openConfirmationModal);
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
  };

  const closeAuthModal = () => {
    authModal.classList.add('hidden');
    authModal.classList.remove('flex');
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
        alert(result.error);
      }
    } catch (err) {
      alert('Login failed');
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
        alert(result.error);
      }
    } catch (err) {
      alert('Registration failed');
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
    document.getElementById('customerName').value = currentUser.full_name || '';
    document.getElementById('customerEmail').value = currentUser.email || '';
    document.getElementById('customerAddress').value = currentUser.shipping_address || '';
    document.getElementById('customerPhone').value = currentUser.phone || '';
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
  button.classList.toggle('hidden', window.scrollY <= 300);
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

function showOrderPendingModal(orderId, email){
  document.getElementById('modalOrderId').textContent = orderId;
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
    alert('Please enter your name, email, address, and phone number.');
    return false;
  }

  if(!/^09\d{9}$/.test(phone)){
    alert('Please enter a valid Philippine mobile number in the format 09123456789.');
    return false;
  }

  return true;
}

async function openConfirmationModal(){
  if(!validateCheckoutFields()) return;

  await calculate();
  const items = document.getElementById('confirmOrderItems');
  items.replaceChildren();
  const cup = findProductById(selectedCupId);
  const lid = findProductById(selectedLidId);
  const microwavable = findProductById(selectedMicrowavableId);
  const cupBoxes = Math.max(0, parseInt(document.getElementById('cupBoxesInput').value || 0, 10));
  const lidBoxes = Math.max(0, parseInt(document.getElementById('lidBoxesInput').value || 0, 10));
  const microwavableBoxes = Math.max(0, parseInt(document.getElementById('microwavableBoxesInput').value || 0, 10));
  const selectedItems = [];

  if(cup && cupBoxes > 0) selectedItems.push(`Cups: ${cup.size} - ${cupBoxes} ${cupBoxes === 1 ? 'box' : 'boxes'}`);
  if(lid && lidBoxes > 0) selectedItems.push(`Lids: ${lid.style} Lid - ${lidBoxes} ${lidBoxes === 1 ? 'box' : 'boxes'}`);
  if(microwavable && microwavableBoxes > 0) selectedItems.push(`Microwavable: ${microwavable.size} - ${microwavableBoxes} ${microwavableBoxes === 1 ? 'box' : 'boxes'}`);

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
  const confirmDownpayment = Number(document.getElementById('total').textContent.replace(/[^0-9.]/g, '') || 0) * 0.5;
  document.getElementById('confirmOrderDownpayment').textContent = formatPrice(confirmDownpayment);
  const modal = document.getElementById('confirmOrderModal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

async function submitOrder(){
  if(!validateCheckoutFields()) return;
  const name = document.getElementById('customerName').value.trim();
  const email = document.getElementById('customerEmail').value.trim();
  const address = document.getElementById('customerAddress').value.trim();
  const phone = document.getElementById('customerPhone').value.trim();
  const cupBoxes = Math.max(0, parseInt(document.getElementById('cupBoxesInput').value || 0, 10));
  const lidId = selectedLidId;
  const lidBoxes = Math.max(0, parseInt(document.getElementById('lidBoxesInput').value || 0, 10));
  const microwavableBoxes = Math.max(0, parseInt(document.getElementById('microwavableBoxesInput').value || 0, 10));
  const cup = findProductById(selectedCupId);
  const lid = findProductById(lidId);
  const microwavable = findProductById(selectedMicrowavableId);

  const payload = {
    // Keep the existing checkout contract while also exposing the requested field names.
    name, address, phone, email,
    fullName: name,
    shippingAddress: address,
    phoneNumber: phone,
    cup_id: selectedCupId,
    cup_size: cup?.size || null,
    cup_boxes: cupBoxes,
    lid_id: lidId,
    lid_style: lid?.style || null,
    lid_boxes: lidBoxes,
    microwavable_id: selectedMicrowavableId,
    microwavable_size: microwavable?.size || null,
    microwavable_boxes: microwavableBoxes
  };

  try{
    // Clear the local cart and close checkout before waiting for the network request.
    resetCheckoutState();
        const res = await fetch(`${API_BASE}/orders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      credentials: 'include'
    });

    const data = await res.json();
    if(!res.ok){
      alert(data.error || 'Failed to place order');
      return;
    }
    showOrderPendingModal(data.order_id, email);
    // Refresh product list to reflect updated stock
    await fetchProducts();
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
