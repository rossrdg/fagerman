const header=document.querySelector('.site-header');
const toggle=document.querySelector('.menu-toggle');
const menu=document.querySelector('.mobile-menu');
window.addEventListener('scroll',()=>header.classList.toggle('scrolled',scrollY>30),{passive:true});
toggle?.addEventListener('click',()=>{const open=menu.classList.toggle('open');toggle.setAttribute('aria-expanded',open)});
menu?.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>{menu.classList.remove('open');toggle.setAttribute('aria-expanded','false')}));
const observer=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting)e.target.classList.add('visible')}),{threshold:.12});
document.querySelectorAll('.reveal').forEach(el=>observer.observe(el));

// ---- Новини: последните публикувани статии от /api/news ----
const NEWS_LIMIT=3;
function newsEl(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e}
function newsDate(iso){
  if(!iso)return '';
  const d=new Date(iso+(iso.endsWith('Z')?'':'Z'));
  return isNaN(d)?'':d.toLocaleDateString('bg-BG',{day:'2-digit',month:'2-digit',year:'numeric'});
}
function newsCard(post,i){
  const href=post.url;
  const card=newsEl('article','news-card reveal');

  const media=newsEl('a','news-img n'+(1+i%3));
  media.href=href;media.setAttribute('aria-label',post.title);
  if(post.cover_image){
    const img=document.createElement('img');
    img.src=post.cover_thumb||post.cover_image;img.alt='';img.loading='lazy';
    media.append(img);
  }else{media.textContent='FA'}

  const body=newsEl('div','news-body');
  const meta=[post.category,newsDate(post.published_at)].filter(Boolean).join(' · ');
  body.append(newsEl('span','',meta||'НОВИНИ'));
  const h3=newsEl('h3');const a=newsEl('a','',post.title);a.href=href;h3.append(a);body.append(h3);
  if(post.excerpt)body.append(newsEl('p','news-excerpt',post.excerpt));

  const actions=newsEl('div','news-actions');
  const more=newsEl('a','text-link','Прочети повече ↗');more.href=href;
  const share=newsEl('a','news-share');
  share.href='https://www.facebook.com/sharer/sharer.php?u='+encodeURIComponent(new URL(href,location.origin).href);
  share.target='_blank';share.rel='noopener noreferrer';
  share.setAttribute('aria-label','Сподели във Facebook');share.title='Сподели във Facebook';
  share.dataset.fbShare='';
  share.innerHTML='<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M13.5 22v-8.2h2.8l.5-3.3h-3.3V8.4c0-.9.4-1.7 1.8-1.7h1.6V3.8s-1.4-.3-2.8-.3c-2.9 0-4.6 1.7-4.6 4.8v2.2H6.7v3.3h2.8V22h4z"/></svg>';
  actions.append(more,share);
  body.append(actions);

  card.append(media,body);
  return card;
}
async function loadNews(){
  const grid=document.querySelector('#newsGrid');
  if(!grid)return;
  try{
    const res=await fetch('/api/news?limit='+NEWS_LIMIT);
    const data=await res.json();
    if(!res.ok||!data.ok)throw new Error('api');
    if(!data.posts.length){
      grid.append(newsEl('p','news-empty','Скоро тук ще публикуваме новини от академията.'));
      return;
    }
    data.posts.forEach((post,i)=>{const c=newsCard(post,i);grid.append(c);observer.observe(c)});
    document.querySelector('#newsMore')?.removeAttribute('hidden');
  }catch(err){
    grid.append(newsEl('p','news-empty','Новините не могат да се заредят в момента. Опитайте отново по-късно.'));
  }
}
// Facebook share: small popup; if it is blocked the link opens normally.
document.addEventListener('click',e=>{
  const a=e.target.closest('[data-fb-share]');
  if(!a)return;
  const w=window.open(a.href,'fbshare','width=640,height=560,noopener');
  if(w)e.preventDefault();
});
// ---- Отбори: от /api/teams (U етикет + набор), подредени от най-малките към мъжете ----
async function loadTeams(){
  const grid=document.querySelector('#teamGrid');
  if(!grid)return;
  try{
    const res=await fetch('/api/teams');
    const data=await res.json();
    if(!res.ok||!data.ok)throw new Error('api');
    if(!data.teams.length){
      grid.append(newsEl('p','team-empty','Отборите ще бъдат публикувани скоро.'));
      return;
    }
    data.teams.forEach((t,i)=>{
      const card=newsEl('article','team-card reveal'+(t.kind==='men'?' accent':''));
      card.append(newsEl('div','team-no',String(i+1).padStart(2,'0')));
      const info=newsEl('div');
      info.append(newsEl('span','',t.cohort_label.toUpperCase()));
      const h3=newsEl('h3');
      const a=newsEl('a','',t.u_label);a.href=t.url;a.setAttribute('aria-label',t.u_label+' — '+t.cohort_label);
      h3.append(a);info.append(h3);
      if(t.description)info.append(newsEl('p','',t.description));
      const arrow=newsEl('a','','→');arrow.href=t.url;arrow.setAttribute('aria-hidden','true');arrow.tabIndex=-1;
      card.append(info,arrow);
      grid.append(card);observer.observe(card);
    });
  }catch(err){
    grid.append(newsEl('p','team-empty','Отборите не могат да се заредят в момента. Опитайте отново по-късно.'));
  }
}
loadNews();
// ---- Снимка на главния треньор (от профила му в админа); без снимка остава placeholder-ът ----
async function loadHeadCoach(){
  const box=document.querySelector('#headCoachPhoto');
  if(!box)return;
  try{
    const res=await fetch('/api/coaches/head');
    const data=await res.json();
    if(!res.ok||!data.ok||!data.photo)return;
    const img=document.createElement('img');
    img.src=data.photo;img.alt=data.name||'Главен треньор';img.loading='lazy';
    img.className='coach-photo-img';
    const placeholder=box.querySelector('.image-placeholder');
    if(placeholder)placeholder.replaceWith(img);else box.prepend(img);
  }catch(err){/* остава placeholder-ът */}
}
loadTeams();
loadHeadCoach();

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

// QR code -> opens this page straight on the registration form on a phone.
const qrEl=document.querySelector('#registrationQr');
if(qrEl && window.QRCode){
  const registrationUrl=window.location.origin+window.location.pathname+'#registration-form';
  new QRCode(qrEl,{text:registrationUrl,width:88,height:88,colorDark:'#07110D',colorLight:'#ffffff'});
}

