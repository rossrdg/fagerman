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

document.querySelector('#registrationForm')?.addEventListener('submit',e=>{
  e.preventDefault();
  const status=e.currentTarget.querySelector('.form-status');
  status.textContent='Благодарим! Демонстрационната форма е изпратена. За production свържете формата със server-side endpoint или form provider.';
  e.currentTarget.reset();
});

document.querySelectorAll('.gallery-item').forEach(btn=>btn.addEventListener('click',()=>{
  alert('Галерия: "'+btn.dataset.label+'". Тук може да бъде включен production lightbox с реалните снимки.');
}));
