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
    const stockClasses = stock > 0 ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-700';
    card.className = 'flex flex-col justify-between overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm';
    card.innerHTML = `
      <div>
        <div class="flex items-start justify-between gap-3 p-5 pb-3">
          <h3 class="font-semibold text-slate-900">${product.name}</h3>
          <span class="shrink-0 rounded-full px-2 py-1 text-xs font-semibold ${stockClasses}">${stockLabel}</span>
        </div>
        <img src="${getProductImage(product)}" alt="${product.name} preview" class="h-40 w-full object-cover" />
        <div class="p-5 pt-4">
          <p class="text-sm font-medium text-slate-700">${product.description}</p>
          <div class="mt-4 flex items-end justify-between gap-3">
            <div>
              <span class="cardPrice text-2xl font-bold text-indigo-700">${formatPrice(product.price_per_box)}</span>
              <span class="cardPriceUnit text-xs font-medium text-slate-700"> / box</span>
            </div>
            <span class="text-xs font-medium text-slate-700">${stock} box(es)</span>
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
  updateConfiguratorActionState();
  // Clearing the cart also clears the City / Location selection, so the next
  // order starts from an explicit location choice again.
  resetDeliveryZone();
  resetDeliveryMethod();
  updateDeliveryAddressVisibility(false);
  syncCategoryTotals();
  updateReservationLimitNote();
  document.getElementById('subtotal').innerText = '₱0.00';
  document.getElementById('shipping').innerText = '₱0.00';
  document.getElementById('total').innerText = '₱0.00';
  updateCartBadges(0);
  document.getElementById('cartContent').innerHTML = '<p class="text-sm text-slate-600">No items in cart.</p>';
  refreshCatalogQuantityInputs();
  updateCheckoutTotals();
}

function updateConfiguratorActionState(){
  // The floating cart FAB remains the entry point to the cart; the hero card
  // no longer includes its own View Cart button.
  return;
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
  // Mirror the shared quantities back onto the matching catalog card inputs
  // AND update each card's dynamic price display so everything stays in sync.
  // Card price = unit price × quantity (total) when qty > 1;
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

// Convert every <i data-lucide="..."> placeholder into an inline SVG. Called
// again after the Order Summary / Confirm Order modal inject new markup.
// Guarded so a blocked Lucide CDN or an unknown icon name never breaks ordering.
function refreshIcons(root){
  if(!window.lucide || typeof window.lucide.createIcons !== 'function') return;
  try {
    window.lucide.createIcons(root ? { root } : undefined);
  } catch (err) {
    // Icons are decorative; ignore conversion errors.
  }
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
  // Track small (12oz) and large (16oz/22oz) cup boxes separately so the
  // per-category totals stay accurate for the checkout payload.
  let cupBoxes = getQtyById('cup-12oz') + getQtyById('cup-16oz') + getQtyById('cup-22oz');
  let smallCupBoxes = getQtyById('cup-12oz');
  let largeCupBoxes = getQtyById('cup-16oz') + getQtyById('cup-22oz');
  let lidBoxes = getQtyById('lid-strawless') + getQtyById('lid-dome') + getQtyById('lid-flat');
  let microwavableBoxes = 0;
  PRODUCTS.forEach(product => {
    const boxes = getQty(product);
    if(product.type === 'cup' && !['cup-12oz', 'cup-16oz', 'cup-22oz'].includes(product.id)){
      cupBoxes += boxes;
      if(isLargeCupProduct(product)) largeCupBoxes += boxes;
      else smallCupBoxes += boxes;
    }
    else if(product.type === 'lid' && !['lid-strawless', 'lid-dome', 'lid-flat'].includes(product.id)) lidBoxes += boxes;
    else if(product.type === 'microwavable') microwavableBoxes += boxes;
  });
  return { cupBoxes, smallCupBoxes, largeCupBoxes, lidBoxes, microwavableBoxes };
}

// Category totals now stay in the shared `qtys` map. They are displayed
// through calculation/order-summary updates; no hero readouts remain.
function syncCategoryTotals(){
  return getCategoryTotals();
}

// Type-in quantities from the removed Quick Configurator inputs are no longer
// supported; catalog cards remain the only quantity entry point.
function distributeCategoryQty(type, total){
  return;
}

function productConfiguratorId(product){
  return null;
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
  //    update Subtotal / Shipping / Final Total in the cart Order Summary.
  //    Re-sync the summed category totals first so catalog card edits are
  //    included in the current calculation.
  syncCategoryTotals();
  // Delivery-radios can be changed programmatically (for example by a reset),
  // so keep hidden/required address fields aligned before totals are calculated.
  updateDeliveryAddressVisibility(getSelectedDeliveryMethod() === DELIVERY_METHOD_SELF_BOOKING);

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

  // Lalamove Delivery (origin: Taguig) = destination base rate + cup/lid box
  // surcharges; the FULL fee always applies (even for 50% downpayment).
  // Microwavables add neither a base rate nor a surcharge.
  // Delivery Method (cart checkout flow):
  //   Option A ('standard')     -> Lalamove local courier fee from the selected
  //     City / Location (#deliveryZone) + cup/lid box surcharges.
  //   Option B ('self_booking') -> Shipping Fee is always P0.00; the customer
  //     books their own rider (Lalamove/Grab) once the order is ready.
  const deliveryMethod = getSelectedDeliveryMethod();
  const selfBooking = deliveryMethod === DELIVERY_METHOD_SELF_BOOKING;
  const totals = getCategoryTotals();
  const deliveryZone = getSelectedDeliveryZone();
  const hasZone = deliveryZone !== '';
  const quote = getLalamoveShipping(totals.cupBoxes, totals.lidBoxes);
  const shipping = (subtotal > 0 && !selfBooking && hasZone) ? quote.fee : 0;
  const shippingLabel = subtotal <= 0
    ? '—'
    : (selfBooking ? SELF_BOOKING_SHIPPING_LABEL : quote.label);
  const total = Math.round((subtotal + shipping) * 100) / 100;

  updateSummary({
    subtotal,
    shipping,
    shippingLabel,
    // Breakdown note only applies to the Lalamove option with a chosen area.
    shippingBreakdown: (!selfBooking && hasZone && subtotal > 0) ? lalamoveBreakdownText(quote) : '',
    needsZone: (!selfBooking && !hasZone && subtotal > 0),
    deliveryMethod,
    deliveryZone,
    deliveryZoneLabel: hasZone ? quote.zoneLabel : '',
    total,
    items
  });

  // The selected City / Location also sets the dynamic payment reservation
  // window shown under the City / Location dropdown.
  updateReservationLimitNote();
}

function isLargeCupProduct(product){
  if(!product || product.type !== 'cup') return false;
  const size = String(product.size || '').trim().toLowerCase();
  if(size === '16oz' || size === '22oz') return true;
  const id = String(product.id || '').trim().toLowerCase();
  return id === 'cup-16oz' || id === 'cup-22oz';
}

function largeCupBoxesInCart(){
  const totals = getCategoryTotals();
  return Math.max(0, parseInt(totals.largeCupBoxes || 0, 10) || 0);
}

function hasLargeCupsInCart(){
  return largeCupBoxesInCart() > 0;
}

// ---------------------------------------------------------------------------
// Delivery Method options for the cart checkout flow.
//   standard     -> Lalamove Delivery (Local Courier Rates): destination base
//                   rate from Taguig + cup/lid box surcharges (mirrors
//                   app.py get_lalamove_shipping_fee).
//   self_booking -> Customer Self-Booking / Warehouse Pick-up: the Shipping
//                   Fee is always P0.00; the customer books their own rider
//                   (Lalamove/Grab) once the order is 'Ready for Pick-up'.
const DELIVERY_METHOD_STANDARD = 'standard';
const DELIVERY_METHOD_SELF_BOOKING = 'self_booking';
const DELIVERY_METHOD_LABELS = {
  [DELIVERY_METHOD_STANDARD]: 'Lalamove Delivery (Local Courier Rates)',
  [DELIVERY_METHOD_SELF_BOOKING]: 'Customer Self-Booking / Warehouse Pick-up'
};
const SELF_BOOKING_SHIPPING_LABEL = 'Customer Self-Booking';
const SELF_BOOKING_NOTE = "Note: You will book your own rider (Lalamove/Grab) once your order status is updated to 'Ready for Pick-up'.";
// Warehouse pick-up address shown in the Confirm Order modal when the
// Customer Self-Booking / Warehouse Pick-up delivery method is selected.
const WAREHOUSE_PICKUP_ADDRESS = '175 M.L.Q. St. Bagumbayan, Taguig City';

// ---------------------------------------------------------------------------
// Lalamove local courier shipping (origin: Taguig City). The destination base
// rate is read from the selected #deliveryZone option, which app.py renders
// from LALAMOVE_ZONE_OPTIONS so the estimate can never drift from the API.
//   Total Shipping Fee = Base Location Rate + Cup Surcharge + Lid Surcharge
//   Cups: 5 + (cupBoxes - 1) * 2      Lids: 3 + (lidBoxes - 1) * 2
// Microwavables add neither a base rate nor a surcharge.
// ---------------------------------------------------------------------------
const LALAMOVE_SHIPPING_LABEL = 'Lalamove';
const CUP_BOX_SURCHARGE_FIRST = 5;
const CUP_BOX_SURCHARGE_ADDITIONAL = 2;
const LID_BOX_SURCHARGE_FIRST = 3;
const LID_BOX_SURCHARGE_ADDITIONAL = 2;

function getDeliveryZoneSelect(){
  return document.getElementById('deliveryZone');
}

// Selected zone id ('' while the customer has not picked a city yet).
function getSelectedDeliveryZone(){
  const select = getDeliveryZoneSelect();
  return select ? String(select.value || '') : '';
}

// Compact zone label of the selected option: prefers the option's data-short
// (e.g. 'Neighboring Cities') so fee lines stay short, mirroring app.py
// delivery_zone_short_label().
function deliveryZoneLabel(){
  const select = getDeliveryZoneSelect();
  if(!select || !select.selectedOptions || select.selectedOptions.length === 0) return '';
  const option = select.selectedOptions[0];
  const short = String(option.dataset.short || '').trim();
  if(short) return short;
  return String(option.textContent || '').split(' — ')[0].trim();
}

// Destination base rate comes straight from the rendered <option data-rate>.
function deliveryZoneRate(){
  const select = getDeliveryZoneSelect();
  if(!select || !select.selectedOptions || select.selectedOptions.length === 0) return 0;
  const rate = parseFloat(select.selectedOptions[0].dataset.rate || '');
  return Number.isFinite(rate) ? rate : 0;
}

// Dynamic payment reservation limit per City / Location. Mirrors app.py
// LALAMOVE_ZONE_RESERVATION_MINUTES / reservation_window_label():
//   Taguig City = 30 minutes, nearby NCR cities = 1 hour, provincial = 2h+.
function reservationWindowLabel(minutes){
  const total = Math.max(0, parseInt(minutes || 0, 10) || 0);
  if(total <= 0) return '—';
  if(total % 60 === 0){
    const hours = total / 60;
    return `${hours} hour${hours === 1 ? '' : 's'}`;
  }
  return `${total} minutes`;
}

// Reservation window (minutes) from the selected option's data-reservation.
function selectedZoneReservationMinutes(){
  const select = getDeliveryZoneSelect();
  if(!select || !select.selectedOptions || select.selectedOptions.length === 0) return 0;
  const minutes = parseInt(select.selectedOptions[0].dataset.reservation || '', 10);
  return Number.isFinite(minutes) ? minutes : 0;
}

// Refresh the City / Location hint stating how long the payment reservation
// (reserved stock + quoted pricing) is held for the selected area.
function updateReservationLimitNote(){
  const note = document.getElementById('reservationLimitNote');
  if(!note) return;
  if(!getSelectedDeliveryZone()){
    note.textContent = 'Select your City / Location to see how long your payment reservation is held.';
    return;
  }
  note.textContent = `Payment reservation limit: ${reservationWindowLabel(selectedZoneReservationMinutes())} from order confirmation (${deliveryZoneLabel()}).`;
}

function cupBoxSurcharge(cupBoxes){
  const cups = Math.max(0, parseInt(cupBoxes || 0, 10) || 0);
  if(cups <= 0) return 0;
  return CUP_BOX_SURCHARGE_FIRST + (cups - 1) * CUP_BOX_SURCHARGE_ADDITIONAL;
}

function lidBoxSurcharge(lidBoxes){
  const lids = Math.max(0, parseInt(lidBoxes || 0, 10) || 0);
  if(lids <= 0) return 0;
  return LID_BOX_SURCHARGE_FIRST + (lids - 1) * LID_BOX_SURCHARGE_ADDITIONAL;
}

// Return the full Lalamove quote for the currently selected City / Location:
// base location rate + cup surcharge + lid surcharge.
function getLalamoveShipping(cupBoxes, lidBoxes){
  if(typeof cupBoxes === 'undefined'){
    const totals = getCategoryTotals();
    cupBoxes = totals.cupBoxes;
    lidBoxes = totals.lidBoxes;
  }
  cupBoxes = Math.max(0, parseInt(cupBoxes || 0, 10) || 0);
  lidBoxes = Math.max(0, parseInt(lidBoxes || 0, 10) || 0);
  const baseRate = deliveryZoneRate();
  const zoneLabel = deliveryZoneLabel();
  const cupSurcharge = cupBoxSurcharge(cupBoxes);
  const lidSurcharge = lidBoxSurcharge(lidBoxes);
  return {
    fee: Math.round((baseRate + cupSurcharge + lidSurcharge) * 100) / 100,
    label: zoneLabel ? `${LALAMOVE_SHIPPING_LABEL} (${zoneLabel})` : LALAMOVE_SHIPPING_LABEL,
    zoneLabel,
    baseRate,
    cupBoxes,
    cupSurcharge,
    lidBoxes,
    lidSurcharge
  };
}

// Order Summary note spelling out how the Lalamove fee was computed.
function lalamoveBreakdownText(shipping){
  if(!shipping) return '';
  const parts = [`${shipping.zoneLabel || 'Location'} base ${formatPrice(shipping.baseRate)}`];
  if(shipping.cupBoxes > 0){
    parts.push(`cups ${shipping.cupBoxes} box${shipping.cupBoxes === 1 ? '' : 'es'} ${formatPrice(shipping.cupSurcharge)}`);
  }
  if(shipping.lidBoxes > 0){
    parts.push(`lids ${shipping.lidBoxes} box${shipping.lidBoxes === 1 ? '' : 'es'} ${formatPrice(shipping.lidSurcharge)}`);
  }
  return parts.join(' + ');
}

// Clear the City / Location selector (used when the cart is cleared/reset).
function resetDeliveryZone(){
  const select = getDeliveryZoneSelect();
  if(select) select.value = '';
}

// Show or hide the shipping price tag (" — ₱XX.XX") attached to every
// City / Location <option>. Customer Self-Booking / Warehouse Pick-up never
// charges a courier fee, so the per-city price tags are stripped from the
// dropdown; Lalamove Delivery restores them. The price-free base label is
// cached on the first run (data-base-label) so toggling back and forth never
// loses text, and option.selected/value are untouched because only the text
// node is rewritten.
function updateDeliveryZonePriceTags(selfBooking){
  const select = getDeliveryZoneSelect();
  if(!select) return;
  Array.from(select.options).forEach(option => {
    const rate = parseFloat(option.dataset.rate || '');
    // The placeholder "Select your city / area" option carries no rate/price.
    if(!Number.isFinite(rate)) return;
    if(!option.dataset.baseLabel){
      option.dataset.baseLabel = String(option.textContent).split(' — ')[0].trim();
    }
    const label = option.dataset.baseLabel;
    option.textContent = selfBooking ? label : `${label} — ${formatPrice(rate)}`;
  });
}

// Read the currently selected Delivery Method radio (defaults to Standard).
function getSelectedDeliveryMethod(){
  const selected = document.querySelector('input[name="delivery_method"]:checked');
  const value = selected ? String(selected.value) : DELIVERY_METHOD_STANDARD;
  return value === DELIVERY_METHOD_SELF_BOOKING ? DELIVERY_METHOD_SELF_BOOKING : DELIVERY_METHOD_STANDARD;
}

function isSelfBookingSelected(){
  return getSelectedDeliveryMethod() === DELIVERY_METHOD_SELF_BOOKING;
}

function deliveryMethodLabel(method){
  return DELIVERY_METHOD_LABELS[method || DELIVERY_METHOD_STANDARD] || DELIVERY_METHOD_LABELS[DELIVERY_METHOD_STANDARD];
}

// Keep delivery address, fee UI and location notes in sync with the chosen
// delivery method.
//   - Self-Booking / Warehouse Pick-up: hides ONLY the Shipping Address field,
//     keeps shipping at P0.00 and relaxes address validation.
//   - Lalamove Delivery: restores the address field, validation, and the
//     location + box surcharge fee.
// City / Location stays visible and enabled for BOTH methods because it also
// sets the dynamic payment reservation window.
function getDeliveryAddressFields(){
  return document.getElementById('deliveryAddressFields');
}

function updateDeliveryAddressVisibility(selfBooking){
  const fields = getDeliveryAddressFields();
  const address = document.getElementById('customerAddress');
  const zone = getDeliveryZoneSelect();
  if(selfBooking && fields){
    fields.classList.add('hidden');
    fields.setAttribute('aria-hidden', 'true');
    if(address) address.removeAttribute('required');
  }else if(fields){
    fields.classList.remove('hidden');
    fields.removeAttribute('aria-hidden');
    if(address) address.setAttribute('required', '');
  }
  // The City / Location selector is never disabled or hidden: it feeds both the
  // Lalamove base rate and the payment reservation limit.
  if(zone){
    zone.removeAttribute('disabled');
    zone.disabled = false;
  }
  // Strip the per-city shipping price tags from the dropdown while
  // Self-Booking / Pick-up is active (shipping is P0.00); Lalamove restores them.
  updateDeliveryZonePriceTags(selfBooking);
  const zoneNote = document.getElementById('deliveryZoneNote');
  if(zoneNote){
    zoneNote.textContent = selfBooking
      ? 'Warehouse pick-up: shipping is free. Your City / Location sets your payment reservation window.'
      : 'Estimated shipping rate calculated based on your location from Taguig + box quantity.';
  }
}

// Delivery Method radio change: refresh fee totals first, then show or hide
// the Lalamove-specific address inputs for that same selection.
function handleDeliveryMethodChange(){
  updateDeliveryAddressVisibility(isSelfBookingSelected());
  calculate();
}

// Restore the default (Option A) selection after the cart is cleared.
function resetDeliveryMethod(){
  const standard = document.getElementById('deliveryMethodStandard');
  if(standard) standard.checked = true;
  updateDeliveryAddressVisibility(false);
}

function updateSummary(data){
  document.getElementById('subtotal').innerText = formatPrice(data.subtotal);
  const shippingLabel = data.shippingLabel || data.shipping_label || '—';
  document.getElementById('shipping').innerText = formatPrice(data.shipping);
  document.getElementById('shipping').title = shippingLabel !== '—' ? `Delivery via ${shippingLabel}` : '';
  document.getElementById('total').innerText = formatPrice(data.total);
  const cartContent = document.getElementById('cartContent');
  if((data.items || []).length === 0){
    cartContent.innerHTML = `<p class="text-sm font-medium text-slate-700">No items in cart.</p>`;
    updateCartBadges(0);
    updateCheckoutTotals();
    refreshIcons();
    return;
  }
  updateCartBadges(data.items.reduce((s,i)=>s+i.boxes,0));
  cartContent.innerHTML = '';
  data.items.forEach(it => {
    const row = document.createElement('div');
    row.className = 'flex items-center justify-between py-2 border-b';
    const boxLabel = Number(it.boxes) === 1 ? 'box' : 'boxes';
    row.innerHTML = `<div><div class="font-medium">${it.name}</div><div class="text-sm font-medium text-slate-700">${it.boxes} ${boxLabel} - ${it.quantity_per_box} units/box</div></div><div class="text-right">${formatPrice(it.line_total)}</div>`;
    cartContent.appendChild(row);
  });
  const totals = document.createElement('div');
  totals.className = 'pt-3';
  const shipLine = shippingLabel && shippingLabel !== '—' ? `Shipping (${shippingLabel})` : 'Shipping';
  // Note under the shipping line of the Order Summary:
  //  - Self-Booking / Pick-up: spell out the rider booking instructions.
  //  - Lalamove with no City / Location yet: prompt for the location.
  //  - Lalamove with a location: show the computed base rate + surcharges.
  let shipNote = '';
  if(data.deliveryMethod === DELIVERY_METHOD_SELF_BOOKING){
    shipNote = `<div class="mt-1 text-xs font-medium leading-5 text-slate-700">${SELF_BOOKING_NOTE}</div>`;
  }else if(data.needsZone){
    shipNote = '<div class="mt-1 text-xs font-medium leading-5 text-slate-700">Select your City / Location to estimate the Lalamove delivery fee.</div>';
  }else if(data.shippingBreakdown){
    shipNote = `<div class="mt-1 text-xs font-medium leading-5 text-slate-700">Lalamove fee: ${data.shippingBreakdown}</div>`;
  }
  totals.innerHTML = `<div class="flex items-center justify-between"><div class="text-sm">Subtotal</div><div class="font-medium">${formatPrice(data.subtotal)}</div></div><div class="flex items-center justify-between mt-2"><div class="text-sm">${shipLine}</div><div class="font-medium">${formatPrice(data.shipping)}</div></div>${shipNote}<div class="flex items-center justify-between mt-3 text-lg font-bold text-indigo-700"><div>Total</div><div>${formatPrice(data.total)}</div></div>`;
  cartContent.appendChild(totals);
  updateCheckoutTotals();
  refreshIcons();
}

function updateCheckoutTotals() {
  const subtotalStr = document.getElementById('subtotal').innerText.replace(/[^0-9.]/g, '');
  const subtotal = parseFloat(subtotalStr) || 0;
  const shippingStr = document.getElementById('shipping').innerText.replace(/[^0-9.]/g, '');
  const shipping = parseFloat(shippingStr) || 0;
  const totalStr = document.getElementById('total').innerText.replace(/[^0-9.]/g, '');
  const total = parseFloat(totalStr) || 0;
  const paymentType = document.getElementById('payment-type-select').value;

  // Estimated Shipping Fee line item in the Order Summary breakdown box. The
  // value mirrors `shipping` — already ₱0.00 for Customer Self-Booking /
  // Warehouse Pick-up, and the live courier estimate for Lalamove Delivery —
  // so the row stays in sync alongside Amount Due Now / Balance upon Delivery.
  const estimatedShippingAmount = document.getElementById('estimated-shipping-amount');
  if (estimatedShippingAmount) estimatedShippingAmount.innerText = formatPrice(shipping);

  // FULL shipping fee is always charged upfront, even for 50% downpayment:
  // Initial Due = (Subtotal * 50%) + Full Shipping; Balance = Subtotal * 50%.
  let dueNow = total;
  let remaining = 0;

  if (paymentType === '50_percent') {
    const downBase = Math.round(subtotal * 0.5 * 100) / 100;
    dueNow = Math.round((downBase + shipping) * 100) / 100;
    remaining = downBase;
    document.getElementById('remaining-balance-row').classList.remove('is-hidden-row');
    document.getElementById('remaining-balance-row').classList.add('is-block-row');
  } else {
    document.getElementById('remaining-balance-row').classList.remove('is-block-row');
    document.getElementById('remaining-balance-row').classList.add('is-hidden-row');
  }

  document.getElementById('due-now-amount').innerText = formatPrice(dueNow);
  document.getElementById('remaining-balance-amount').innerText = formatPrice(remaining);
}

// Keep the floating (#floating-cart-badge) cart count in sync whenever the
// cart contents change. The header icon is now the Order History button
// (#nav-orders-btn), so it no longer shows a cart count badge.
function updateCartBadges(count){
  const floatingBadge = document.getElementById('floating-cart-badge');
  if(floatingBadge) floatingBadge.innerText = String(count);
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

// Alias used by the floating cart button's inline onclick handler.
function openCartModal(){
  openCart();
}

// "Clear All" in the Order Summary header: reset every item quantity to 0 and
// let the shared calculator push P0.00 back into the Order Summary totals and
// the checkout fields, while keeping the City / Location and Delivery Method
// selections the customer already made.
async function clearCartItems(){
  selectedCupId = null;
  selectedLidId = null;
  selectedMicrowavableId = null;
  Object.keys(qtys).forEach(id => delete qtys[id]);
  refreshCatalogQuantityInputs();
  updateConfiguratorActionState();
  await calculate();
  refreshIcons();
  showToast('Cart cleared — all item quantities reset to 0.');
}


// ---------------------------------------------------------------------------
// GCash payment details for the checkout drawer's Payment Instructions box
// (#gcashAccountName / #gcashAccountNumber). Mirrors app.py's
// GCASH_ACCOUNT_NAME / GCASH_ACCOUNT_NUMBER so the drawer, PDF receipt and
// confirmation email always show the same wallet details.
// ---------------------------------------------------------------------------
const GCASH_ACCOUNT_NAME = 'Rhea E.';
const GCASH_ACCOUNT_NUMBER = '0928 181 5599';

function renderGcashInstructions(){
  const nameEl = document.getElementById('gcashAccountName');
  if(nameEl) nameEl.textContent = GCASH_ACCOUNT_NAME;
  const numberEl = document.getElementById('gcashAccountNumber');
  if(numberEl) numberEl.textContent = GCASH_ACCOUNT_NUMBER;
}

// Event wiring
document.addEventListener('DOMContentLoaded', () => {
  resetConfigurator();
  fetchProducts();
  // Push the GCash account details into the drawer's Payment Instructions box.
  renderGcashInstructions();
  document.getElementById('customerPhone').addEventListener('input', function(){
    this.value = this.value.replace(/[^0-9]/g, '');
    if(this.value.length > 0 && !this.value.startsWith('09')){
      this.value = this.value.startsWith('9')
        ? `0${this.value}`
        : `09${this.value.replace(/^0+/, '')}`;
    }
    this.value = this.value.slice(0, 11);
  });
  const checkoutForm = document.getElementById('checkoutForm');
  if(checkoutForm){
    checkoutForm.addEventListener('submit', (e) => {
      e.preventDefault();
      openConfirmationModal();
    });
  }
  // The header cart icon was replaced by the Order History button
  // (#nav-orders-btn), which uses an inline onclick routing to
  // handleNavOrdersClick(). The floating cart FAB remains the cart entry point.
  document.getElementById('closeCart').addEventListener('click', closeCart);
  // "Clear All" resets every quantity to 0 and zeroes the Order Summary totals.
  document.getElementById('clearCartBtn').addEventListener('click', clearCartItems);
  // Explicit backdrop overlay dismiss: the dimmed .cart-overlay element sits
  // below the panel and only accepts pointer events while the drawer is open,
  // so tapping/clicking ANYWHERE outside the Order Summary panel closes it.
  const cartOverlay = document.getElementById('cartOverlay');
  if (cartOverlay) {
    cartOverlay.addEventListener('click', (e) => {
      // Stop the click from also bubbling into the container fallback below.
      e.stopPropagation();
      closeCart();
    });
  }
  // Fallback dismiss: if the overlay element is missing (or its CSS failed to
  // load) the container itself is still a valid click target while open.
  const cartDrawer = document.getElementById('cartDrawer');
  if (cartDrawer) {
    cartDrawer.addEventListener('click', (e) => {
      if (e.target === cartDrawer) closeCart();
    });
  }
  // Keyboard equivalent of the backdrop dismiss: Escape closes the Order
  // Summary panel, unless a dialog is stacked on top of it.
  document.addEventListener('keydown', (e) => {
    if(e.key !== 'Escape') return;
    if(!document.body.classList.contains('drawer-open')) return;
    const confirmModal = document.getElementById('confirmOrderModal');
    if(confirmModal && !confirmModal.classList.contains('hidden')) return;
    closeCart();
  });
  document.getElementById('addMoreItemsBtn').addEventListener('click', closeConfirmationModal);
  document.getElementById('confirmOrderBtn').addEventListener('click', submitOrder);
  document.getElementById('closeModalBtn').addEventListener('click', closeOrderPendingModal);
  setupAuthModal();
  setupAccountNudgeModal();
  setupCustomerOrdersModal();
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

  // Forgot password modal wiring
  const forgotPasswordBtn = document.getElementById('forgotPasswordBtn');
  const closeForgotPasswordBtn = document.getElementById('closeForgotPassword');
  const backToAuthBtn = document.getElementById('backToAuthBtn');
  const forgotPasswordForm = document.getElementById('forgotPasswordForm');
  const forgotPasswordModal = document.getElementById('forgot-password-modal');

  if(forgotPasswordBtn) forgotPasswordBtn.addEventListener('click', showForgotPassword);
  if(closeForgotPasswordBtn) closeForgotPasswordBtn.addEventListener('click', closeForgotPassword);
  if(backToAuthBtn) backToAuthBtn.addEventListener('click', backToAuthModal);
  if(forgotPasswordForm){
    forgotPasswordForm.addEventListener('submit', (e) => {
      e.preventDefault();
      handleResetPassword();
    });
  }
  if(forgotPasswordModal){
    forgotPasswordModal.addEventListener('click', (e) => {
      if(e.target === forgotPasswordModal) closeForgotPassword();
    });
  }
  document.addEventListener('keydown', (e) => {
    if(e.key === 'Escape') closeForgotPassword();
  });

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


  document.getElementById('logoutBtn').addEventListener('click', logout);
  // Render the static Lucide icon placeholders (Clear All, Close, modal icons).
  refreshIcons();

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

// Opens the Login / Register modal. Used by the navbar Order History button's
// inline onclick so guests are prompted to sign in before viewing orders.
function openAuthModal(){
  const authModal = document.getElementById('authModal');
  if(!authModal) return;
  authModal.classList.remove('hidden');
  authModal.classList.add('flex');
  document.body.classList.add('modal-open');

  // Default to the Login tab so guests are prompted to sign in.
  const tabLogin = document.getElementById('tabLogin');
  const tabRegister = document.getElementById('tabRegister');
  const loginForm = document.getElementById('loginForm');
  const registerForm = document.getElementById('registerForm');
  if(tabLogin && tabRegister && loginForm && registerForm){
    tabLogin.classList.add('border-indigo-600', 'text-indigo-600');
    tabLogin.classList.remove('border-transparent', 'text-slate-500');
    tabRegister.classList.add('border-transparent', 'text-slate-500');
    tabRegister.classList.remove('border-indigo-600', 'text-indigo-600');
    loginForm.classList.remove('hidden');
    registerForm.classList.add('hidden');
  }
}

// Forgot password flow: the login tab links here to let a customer set a new
// password for their own account from the reset modal.
function showForgotPassword(){
  const modal = document.getElementById('forgot-password-modal');
  if(!modal) return;

  // Close the login/register modal so the reset dialog is the only one open.
  const authModal = document.getElementById('authModal');
  if(authModal){
    authModal.classList.add('hidden');
    authModal.classList.remove('flex');
  }

  const errorBox = document.getElementById('forgotPasswordError');
  if(errorBox){
    errorBox.textContent = '';
    errorBox.classList.add('hidden');
  }

  modal.classList.remove('hidden');
  modal.classList.add('flex');
  document.body.classList.add('modal-open');

  const emailInput = document.getElementById('resetEmail');
  if(emailInput) emailInput.focus();
}

function closeForgotPassword(){
  const modal = document.getElementById('forgot-password-modal');
  if(!modal || modal.classList.contains('hidden')) return;

  modal.classList.add('hidden');
  modal.classList.remove('flex');
  document.body.classList.remove('modal-open');

  const errorBox = document.getElementById('forgotPasswordError');
  if(errorBox){
    errorBox.textContent = '';
    errorBox.classList.add('hidden');
  }

  const form = document.getElementById('forgotPasswordForm');
  if(form) form.reset();
}

// Back button in the reset dialog: discard the reset form and return to the
// Login / Register modal so customers can sign in instead.
function backToAuthModal(){
  closeForgotPassword();
  openAuthModal();
}

async function handleResetPassword(){
  const form = document.getElementById('forgotPasswordForm');
  if(!form) return;

  const submitButton = form.querySelector('button[type="submit"]');
  const errorBox = document.getElementById('forgotPasswordError');
  const email = (document.getElementById('resetEmail').value || '').trim();
  const newPassword = document.getElementById('resetNewPassword').value || '';

  const showResetError = (text) => {
    if(!errorBox) return;
    errorBox.textContent = text;
    errorBox.classList.remove('hidden');
  };

  if(errorBox){
    errorBox.textContent = '';
    errorBox.classList.add('hidden');
  }

  if(!email || !newPassword){
    showResetError('Email address and new password are required.');
    return;
  }
  if(newPassword.length < 8){
    showResetError('New password must be at least 8 characters.');
    return;
  }

  if(submitButton){
    submitButton.disabled = true;
    submitButton.textContent = 'Resetting...';
  }

  try {
    const res = await fetch(`${API_BASE}/reset-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email, new_password: newPassword }),
      credentials: 'include'
    });
    const result = await res.json().catch(() => ({}));

    if(res.ok){
      closeForgotPassword();
      showCustomAlert(result.message || 'Your password has been reset. You can now log in.');
    } else {
      showResetError(result.error || 'Unable to reset password.');
    }
  } catch (err) {
    showResetError('Unable to reset password. Please try again.');
  } finally {
    if(submitButton){
      submitButton.disabled = false;
      submitButton.textContent = 'Reset Password';
    }
  }
}

// Sign the customer out: invalidate the server session, clear browser storage
// and the checkout fields, then hard-reset the UI back to the guest state.
async function logout(){
  try {
    await fetch(`${API_BASE}/logout`, {
      method: 'POST',
      credentials: 'include'
    });
  } catch (err) {
    // Best-effort: still clear local state if the server is unreachable.
  }

  currentUser = null;
  localStorage.clear();
  sessionStorage.clear();

  // Explicitly clear the checkout input values (name, email, address, phone).
  document.getElementById('customerName').value = '';
  document.getElementById('customerEmail').value = '';
  document.getElementById('customerAddress').value = '';
  document.getElementById('customerPhone').value = '';

  // Hard-reset the UI back to the guest state.
  window.location.reload();
}

function updateAuthUI(){
  const authBtn = document.getElementById('authBtn');
  const logoutBtn = document.getElementById('logoutBtn');
  if (currentUser) {
    authBtn.textContent = currentUser.full_name;
    authBtn.disabled = true;
    logoutBtn.classList.remove('hidden');
    wrapUsernameAsOrdersButton();
  } else {
    authBtn.textContent = 'Login / Register';
    authBtn.disabled = false;
    logoutBtn.classList.add('hidden');
    unwrapUsernameAsOrdersButton();
  }
}

function wrapUsernameAsOrdersButton(){
  // Wrap the navbar username inside a clickable button that opens the
  // customer orders modal, so customers can check order status.
  const authBtn = document.getElementById('authBtn');
  const parent = authBtn && authBtn.parentNode;
  if(!authBtn || !parent) return;
  if(parent.getAttribute && parent.getAttribute('data-orders-wrap') === 'true') return;

  const nextSibling = authBtn.nextElementSibling;
  const wrapper = document.createElement('button');
  wrapper.type = 'button';
  wrapper.className = 'hover:text-slate-900';
  wrapper.setAttribute('data-orders-wrap', 'true');
  wrapper.setAttribute('onclick', 'openCustomerOrders()');
  wrapper.setAttribute('aria-label', `Check order status for ${currentUser.full_name}`);
  wrapper.appendChild(authBtn);
  if(nextSibling){
    parent.insertBefore(wrapper, nextSibling);
  } else {
    parent.appendChild(wrapper);
  }
  // The disabled user button must not swallow clicks meant for the wrapper.
  authBtn.style.pointerEvents = 'none';
  authBtn.title = 'View order status';
}

function unwrapUsernameAsOrdersButton(){
  const authBtn = document.getElementById('authBtn');
  if(!authBtn) return;
  authBtn.style.pointerEvents = '';
  authBtn.removeAttribute('title');
  const parent = authBtn.parentNode;
  if(parent && parent.getAttribute && parent.getAttribute('data-orders-wrap') === 'true'){
    parent.replaceWith(authBtn);
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



// Navbar Order History button: signed-in customers see their order history;
// guests see an account recommendation instead of being blocked silently.
function handleNavOrdersClick(){
  if(currentUser){
    openCustomerOrders();
  } else {
    openAccountNudgeModal();
  }
}

// Guest account recommendation: explain the benefits, offer login/register,
// or let the visitor continue as a guest. Returns focus behavior consistent
// with the auth and orders modals.
function openAccountNudgeModal(){
  const modal = document.getElementById('accountNudgeModal');
  if(!modal) return;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  document.body.classList.add('modal-open');
}

function closeAccountNudgeModal(){
  const modal = document.getElementById('accountNudgeModal');
  if(!modal || modal.classList.contains('hidden')) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
  if(document.getElementById('authModal').classList.contains('hidden')
    && document.getElementById('customer-orders-modal').classList.contains('hidden')
    && document.getElementById('orderPendingModal').classList.contains('hidden')
    && document.getElementById('confirmOrderModal').classList.contains('hidden')){
    document.body.classList.remove('modal-open');
  }
}

function openAuthModalWithTab(tab){
  openAuthModal();
  const loginForm = document.getElementById('loginForm');
  const registerForm = document.getElementById('registerForm');
  const tabLogin = document.getElementById('tabLogin');
  const tabRegister = document.getElementById('tabRegister');
  if(!loginForm || !registerForm || !tabLogin || !tabRegister) return;
  const showRegister = tab === 'register';
  loginForm.classList.toggle('hidden', showRegister);
  registerForm.classList.toggle('hidden', !showRegister);
  tabLogin.classList.toggle('border-indigo-600', !showRegister);
  tabLogin.classList.toggle('text-indigo-600', !showRegister);
  tabLogin.classList.toggle('border-transparent', showRegister);
  tabLogin.classList.toggle('text-slate-500', showRegister);
  tabRegister.classList.toggle('border-indigo-600', showRegister);
  tabRegister.classList.toggle('text-indigo-600', showRegister);
  tabRegister.classList.toggle('border-transparent', !showRegister);
  tabRegister.classList.toggle('text-slate-500', !showRegister);
}

function setupAccountNudgeModal(){
  const modal = document.getElementById('accountNudgeModal');
  const loginBtn = document.getElementById('accountNudgeLoginBtn');
  const registerBtn = document.getElementById('accountNudgeRegisterBtn');
  const dismissBtn = document.getElementById('accountNudgeDismissBtn');
  if(!modal || !loginBtn || !registerBtn || !dismissBtn) return;

  const openAuthTab = (tab) => {
    closeAccountNudgeModal();
    openAuthModalWithTab(tab);
  };
  loginBtn.addEventListener('click', () => openAuthTab('login'));
  registerBtn.addEventListener('click', () => openAuthTab('register'));
  dismissBtn.addEventListener('click', closeAccountNudgeModal);
  modal.addEventListener('click', event => {
    if(event.target === modal) closeAccountNudgeModal();
  });
  document.addEventListener('keydown', event => {
    if(event.key === 'Escape' && !modal.classList.contains('hidden')) closeAccountNudgeModal();
  });
}

function openCustomerOrders(){
  const modal = document.getElementById('customer-orders-modal');
  const list = document.getElementById('customer-orders-list');
  if(!modal || !list) return;

  if(!currentUser){
    openAccountNudgeModal();
    return;
  }

  modal.classList.remove('hidden');
  modal.classList.add('flex');
  document.body.classList.add('modal-open');

  list.innerHTML = '';
  const loading = document.createElement('p');
  loading.className = 'text-sm font-medium text-slate-700';
  loading.textContent = 'Loading your orders…';
  list.appendChild(loading);

  fetch(`${API_BASE}/user/orders`, { credentials: 'include' })
    .then(res => res.json())
    .then(data => {
      if(data.orders === undefined){
        list.innerHTML = '';
        const msg = document.createElement('p');
        msg.className = 'text-sm text-red-600';
        msg.textContent = data.error || 'Could not load your orders.';
        list.appendChild(msg);
        return;
      }
      renderCustomerOrders(data.orders);
    })
    .catch(() => {
      list.innerHTML = '';
      const msg = document.createElement('p');
      msg.className = 'text-sm text-red-600';
      msg.textContent = 'Network error loading your orders. Please try again.';
      list.appendChild(msg);
    });
}

const CUSTOMER_ORDER_BADGES = {
  Pending: 'bg-amber-100 text-amber-800',
  Paid: 'bg-sky-100 text-sky-700',
  'Ready for Pick-up': 'bg-emerald-100 text-emerald-700',
  Shipping: 'bg-indigo-100 text-indigo-700',
  Completed: 'bg-emerald-100 text-emerald-800'
};

function orderStatusBadge(status){
  const classes = CUSTOMER_ORDER_BADGES[status] || 'bg-slate-100 text-slate-700';
  const label = status || 'Pending';
  return `<span class="shrink-0 rounded-full px-2 py-1 text-xs font-semibold ${classes}">${escapeHtml(label)}</span>`;
}

function orderItemsSummary(order){
  const lines = [];
  const cupBoxes = Number(order.cup_boxes || 0);
  const lidBoxes = Number(order.lid_boxes || 0);
  const microBoxes = Number(order.microwavable_boxes || 0);
  if(cupBoxes > 0) lines.push(`Cups: ${escapeHtml(order.cup_size || 'Selected size')} — ${cupBoxes} box(es)`);
  if(lidBoxes > 0) lines.push(`Lids: ${escapeHtml(order.lid_style || 'Selected style')} — ${lidBoxes} box(es)`);
  if(microBoxes > 0) lines.push(`Containers: ${escapeHtml(order.microwavable_size || 'Selected size')} — ${microBoxes} box(es)`);
  return lines.length > 0 ? lines.join('<br>') : '<span class="font-medium text-slate-600">No item details.</span>';
}

function formatOrderDate(value){
  if(!value) return '';
  const date = new Date(value);
  if(isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function renderCustomerOrders(orders){
  const list = document.getElementById('customer-orders-list');
  if(!list) return;
  list.innerHTML = '';

  if(!orders || orders.length === 0){
    const empty = document.createElement('p');
    empty.className = 'text-sm font-medium text-slate-700';
    empty.textContent = 'No orders found for your account yet.';
    list.appendChild(empty);
    return;
  }

  orders.forEach(order => {
    const card = document.createElement('div');
    card.className = 'rounded-lg border border-slate-200 bg-white p-4';
    card.innerHTML = `
      <div class="flex items-center justify-between gap-3">
        <span class="font-semibold text-indigo-700">Order #${escapeHtml(order.id)}</span>
        ${orderStatusBadge(order.status)}
      </div>
      <p class="mt-1 text-xs font-medium text-slate-700">${escapeHtml(formatOrderDate(order.created_at))}</p>
      <div class="mt-1 text-sm font-medium leading-5 text-slate-700">${orderItemsSummary(order)}</div>
      <div class="mt-1 flex items-end justify-between gap-3">
        <span class="text-sm font-semibold text-slate-800">Total: ${formatPrice(order.total_amount)}</span>
        <span class="text-xs font-medium text-slate-700">${escapeHtml(order.payment_status || '')}</span>
      </div>
    `;
    list.appendChild(card);
  });
}

function setupCustomerOrdersModal(){
  const modal = document.getElementById('customer-orders-modal');
  const closeBtn = document.getElementById('closeCustomerOrders');
  if(!modal || !closeBtn) return;

  const close = () => {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.body.classList.remove('modal-open');
  };

  closeBtn.addEventListener('click', close);
  modal.addEventListener('click', event => {
    if(event.target === modal) close();
  });
  document.addEventListener('keydown', event => {
    if(event.key === 'Escape' && !modal.classList.contains('hidden')) close();
  });
}

function escapeHtml(value){
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function debounce(fn, wait){
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(()=>fn(...args), wait); };
}

function scrollToCatalog(event){
  if(event) event.preventDefault();
  const catalog = document.getElementById('catalog');
  if(catalog){
    catalog.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
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
  const wasGuestCheckout = !currentUser;
  setTimeout(() => {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    // Guests finishing checkout see the account recommendation after the
    // pending confirmation closes, so tracking/faster checkout is discoverable.
    if(wasGuestCheckout) openAccountNudgeModal();
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
  resetDeliveryMethod();
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
  const selfBooking = isSelfBookingSelected();

  if(!name || !email || !phone || (!selfBooking && !address)){
    showCustomAlert(selfBooking
      ? 'Please enter your name, email, and phone number.'
      : 'Please enter your name, email, address, and phone number.');
    return false;
  }

  if(!/^09\d{9}$/.test(phone)){
    showCustomAlert('Please enter a valid Philippine mobile number in the format 09123456789.');
    return false;
  }

  // City / Location is required for BOTH delivery methods: it drives the
  // Lalamove base rate and the dynamic payment reservation window.
  if(!getSelectedDeliveryZone()){
    showCustomAlert('Please select your City / Location so we can set your delivery fee and payment reservation window.');
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
  // FULL shipping always upfront: Due = (Subtotal*50%) + Full Shipping.
  const downBase = Math.round(subtotal * 0.5 * 100) / 100;
  const dueNow = paymentType === '50_percent' ? Math.round((downBase + shipping) * 100) / 100 : total;
  const remaining = paymentType === '50_percent' ? downBase : 0;

  setHidden('checkoutCupId', cup.product ? cup.product.id : '');
  setHidden('checkoutCupSize', cup.product?.size || '');
  setHidden('checkoutCupBoxes', cupBoxes);
  setHidden('checkoutLidId', lid.product ? lid.product.id : '');
  setHidden('checkoutLidStyle', lid.product?.style || '');
  setHidden('checkoutLidBoxes', lidBoxes);
  setHidden('checkoutMicrowavableId', micro.product ? micro.product.id : '');
  setHidden('checkoutMicrowavableSize', micro.product?.size || '');
  setHidden('checkoutMicrowavableBoxes', microBoxes);
  setHidden('checkoutHasLargeCups', cupItems.some(i => isLargeCupProduct(i.product)) ? '1' : '0');
  setHidden('checkoutSmallCupBoxes', cupItems.reduce((s, i) => s + (isLargeCupProduct(i.product) ? 0 : i.boxes), 0));
  setHidden('checkoutLargeCupBoxes', cupItems.reduce((s, i) => s + (isLargeCupProduct(i.product) ? i.boxes : 0), 0));
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
    items.innerHTML = '<p class="font-medium text-slate-700">No items selected.</p>';
  }else{
    selectedItems.forEach(item => {
      const line = document.createElement('div');
      line.textContent = item;
      items.appendChild(line);
    });
  }

  document.getElementById('confirmOrderTotal').textContent = document.getElementById('total').textContent;

  const subtotalAmount = Number(document.getElementById('subtotal').textContent.replace(/[^0-9.]/g, '') || 0);
  const shippingAmount = Number(document.getElementById('shipping').textContent.replace(/[^0-9.]/g, '') || 0);
  const totalAmount = Number(document.getElementById('total').textContent.replace(/[^0-9.]/g, '') || 0);
  // Delivery Method: Option B (self-booking) always shows a P0.00 shipping fee;
  // Option A shows the Lalamove zone fee (base rate + cup/lid surcharges).
  const deliveryMethod = getSelectedDeliveryMethod();
  const selfBooking = deliveryMethod === DELIVERY_METHOD_SELF_BOOKING;
  const shippingLabel = selfBooking
    ? SELF_BOOKING_SHIPPING_LABEL
    : ((document.getElementById('shipping').title || '').replace(/^Delivery via /, '') || LALAMOVE_SHIPPING_LABEL);
  const paymentType = document.getElementById('payment-type-select').value;
  const fullRow = document.getElementById('confirmOrderFullRow');
  const downpaymentRow = document.getElementById('confirmOrderDownpaymentRow');
  const paymentNote = document.getElementById('confirmOrderPaymentNote');
  const deliveryMethodField = document.getElementById('confirmOrderDeliveryMethod');
  if (deliveryMethodField) {
    deliveryMethodField.textContent = selfBooking
      ? 'Self-Booking / Warehouse Pick-up'
      : DELIVERY_METHOD_LABELS[DELIVERY_METHOD_STANDARD];
  }
  const deliveryZoneField = document.getElementById('confirmOrderDeliveryZone');
  if (deliveryZoneField) {
    deliveryZoneField.textContent = selfBooking
      ? '—'
      : (deliveryZoneLabel() || 'Not selected');
  }

  // Dynamic payment reservation window for the selected City / Location.
  const reservationNote = document.getElementById('confirmOrderReservationNote');
  if (reservationNote) {
    reservationNote.textContent = getSelectedDeliveryZone()
      ? `⏳ Reserved for ${reservationWindowLabel(selectedZoneReservationMinutes())} from confirmation (${deliveryZoneLabel()}) — send your GCash payment within this window.`
      : '';
  }

  // Address line: Self-Booking shows the Taguig Warehouse Pick-up Address;
  // Lalamove Delivery shows the customer's Shipping Address instead
  // (the row stays hidden when there is no address to show).
  const addressRow = document.getElementById('confirmOrderAddressRow');
  const addressText = document.getElementById('confirmOrderAddressText');
  if (addressRow && addressText) {
    if (selfBooking) {
      addressText.textContent = `Pick-up Address: ${WAREHOUSE_PICKUP_ADDRESS}`;
      addressRow.classList.remove('is-hidden-row');
      addressRow.classList.add('is-flex-row');
    } else {
      const shippingAddress = document.getElementById('customerAddress').value.trim();
      if (shippingAddress) {
        addressText.textContent = `Shipping Address: ${shippingAddress}`;
        addressRow.classList.remove('is-hidden-row');
        addressRow.classList.add('is-flex-row');
      } else {
        addressRow.classList.remove('is-flex-row');
        addressRow.classList.add('is-hidden-row');
      }
    }
  }

  if (paymentType === 'full') {
    // 100% Full Payment: show the full total as the required payment.
    fullRow.classList.remove('is-hidden-row');
    fullRow.classList.add('is-flex-row');
    downpaymentRow.classList.remove('is-flex-row');
    downpaymentRow.classList.add('is-hidden-row');
    document.getElementById('confirmOrderRequiredPayment').textContent = formatPrice(totalAmount);
    paymentNote.textContent = selfBooking
      ? `Full payment (${formatPrice(subtotalAmount)} items) required via GCash. ${SELF_BOOKING_NOTE}`
      : `Full payment (${formatPrice(subtotalAmount)} items + ${formatPrice(shippingAmount)} ${shippingLabel} shipping) required via GCash.`;
  } else {
    // 50% Downpayment: Due = (Subtotal*50%) + FULL shipping; Balance = Subtotal*50%.
    fullRow.classList.remove('is-flex-row');
    fullRow.classList.add('is-hidden-row');
    downpaymentRow.classList.remove('is-hidden-row');
    downpaymentRow.classList.add('is-flex-row');
    const downBase = Math.round(subtotalAmount * 0.5 * 100) / 100;
    const confirmDownpayment = Math.round((downBase + shippingAmount) * 100) / 100;
    document.getElementById('confirmOrderDownpayment').textContent = formatPrice(confirmDownpayment);
    document.getElementById('confirmOrderDownpaymentRow').firstElementChild.textContent = selfBooking
      ? 'Required Initial (50% items + ₱0.00 shipping)'
      : `Required Initial (50% items + full ${shippingLabel} shipping)`;
    paymentNote.textContent = selfBooking
      ? `A ${formatPrice(downBase)} downpayment (50% of items) = ${formatPrice(confirmDownpayment)} is required via GCash. The remaining ${formatPrice(downBase)} balance will be paid upon pick-up. ${SELF_BOOKING_NOTE}`
      : `A ${formatPrice(downBase)} downpayment (50% of items) + ${formatPrice(shippingAmount)} full ${shippingLabel} shipping = ${formatPrice(confirmDownpayment)} is required via GCash. The remaining ${formatPrice(downBase)} balance will be paid upon delivery.`;
  }

  const modal = document.getElementById('confirmOrderModal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  // Lucide placeholders inside the modal are converted on first open.
  refreshIcons(modal);
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
