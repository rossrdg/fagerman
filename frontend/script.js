const header=document.querySelector('.site-header');
const toggle=document.querySelector('.menu-toggle');
const menu=document.querySelector('.mobile-menu');
window.addEventListener('scroll',()=>header.classList.toggle('scrolled',scrollY>30),{passive:true});
toggle?.addEventListener('click',()=>{const open=menu.classList.toggle('open');toggle.setAttribute('aria-expanded',open)});
menu?.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>{menu.classList.remove('open');toggle.setAttribute('aria-expanded','false')}));
const observer=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting)e.target.classList.add('visible')}),{threshold:.12});
document.querySelectorAll('.reveal').forEach(el=>observer.observe(el));

const modal=document.querySelector('#newsModal');
const modalTitle=document.querySelector('#modalTitle');
const modalText=document.querySelector('#modalText');
document.querySelectorAll('.news-open').forEach(btn=>btn.addEventListener('click',()=>{
  modalTitle.textContent=btn.dataset.title; modalText.textContent=btn.dataset.text;
  modal.classList.add('open'); modal.setAttribute('aria-hidden','false');
}));
function closeModal(){modal.classList.remove('open');modal.setAttribute('aria-hidden','true')}
document.querySelector('.modal-close')?.addEventListener('click',closeModal);
document.querySelector('.modal-backdrop')?.addEventListener('click',closeModal);
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal()});

const FIELD_LABELS={
  child:'Име на детето', age:'Възраст', parent:'Име на родител', phone:'Телефон', email:'Email'
};

document.querySelector('#registrationForm')?.addEventListener('submit',async e=>{
  e.preventDefault();
  const form=e.currentTarget;
  const status=form.querySelector('.form-status');
  const submitBtn=form.querySelector('button[type="submit"]');

  form.querySelectorAll('.field-error').forEach(el=>el.classList.remove('field-error'));
  status.className='form-status';
  status.textContent='Изпраща се...';
  submitBtn.disabled=true;

  const payload=Object.fromEntries(new FormData(form).entries());

  try{
    const res=await fetch('/api/registration',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)
    });
    const data=await res.json();

    if(res.ok && data.ok){
      status.classList.add('success');
      status.textContent='Благодарим! Заявката Ви е получена — ще се свържем с Вас с предложение за дата и час.';
      form.reset();
    }else if(data.errors){
      status.classList.add('error');
      const messages=Object.entries(data.errors).map(([field,msg])=>{
        const input=form.querySelector(`[name="${field}"]`);
        input?.classList.add('field-error');
        return `${FIELD_LABELS[field]||field}: ${msg}`;
      });
      status.textContent=messages.join(' ');
    }else{
      status.classList.add('error');
      status.textContent='Нещо се обърка. Моля, опитайте отново по-късно.';
    }
  }catch(err){
    status.classList.add('error');
    status.textContent='Няма връзка със сървъра. Моля, проверете интернет връзката си и опитайте пак.';
  }finally{
    submitBtn.disabled=false;
  }
});

const galleryModal=document.querySelector('#galleryModal');
const lightboxImg=document.querySelector('#lightboxImg');
const lightboxLabel=document.querySelector('#lightboxLabel');
function openLightbox(btn){
  lightboxImg.src=btn.dataset.full||btn.querySelector('img')?.src||'';
  lightboxImg.alt=btn.dataset.label||'';
  lightboxLabel.textContent=btn.dataset.label||'';
  galleryModal.classList.add('open');
  galleryModal.setAttribute('aria-hidden','false');
}
function closeLightbox(){
  galleryModal.classList.remove('open');
  galleryModal.setAttribute('aria-hidden','true');
  lightboxImg.src='';
}
document.querySelectorAll('.gallery-item').forEach(btn=>btn.addEventListener('click',()=>openLightbox(btn)));
galleryModal?.querySelector('.lightbox-close')?.addEventListener('click',closeLightbox);
galleryModal?.querySelector('.modal-backdrop')?.addEventListener('click',closeLightbox);
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeLightbox()});

// QR code -> opens this page straight on the registration form on a phone.
const qrEl=document.querySelector('#registrationQr');
if(qrEl && window.QRCode){
  const registrationUrl=window.location.origin+window.location.pathname+'#registration-form';
  new QRCode(qrEl,{text:registrationUrl,width:88,height:88,colorDark:'#07110D',colorLight:'#ffffff'});
}

