'use strict';
(()=>{
const root=document.documentElement,key='wnba-theme';
const read=()=>{try{const value=localStorage.getItem(key);return ['dark','light'].includes(value)?value:null;}catch{return null;}};
function apply(theme){
root.dataset.theme=theme;
const button=document.querySelector('#theme-toggle');if(!button)return;
const dark=theme==='dark';button.textContent=dark?'☀':'☾';button.setAttribute('aria-pressed',String(dark));
button.setAttribute('aria-label',dark?'Switch to light mode':'Switch to dark mode');button.title=dark?'Switch to light mode':'Switch to dark mode';
}
apply(read()||'light');
function bind(){const button=document.querySelector('#theme-toggle');if(!button)return;apply(root.dataset.theme);button.addEventListener('click',()=>{const theme=root.dataset.theme==='dark'?'light':'dark';apply(theme);try{localStorage.setItem(key,theme);}catch{}});}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
})();
