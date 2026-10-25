(() => {
 const frame=document.getElementById('adStudioFrame');
 const api=()=>frame.contentWindow?.AdStudio;
 document.getElementById('graphFilmExport').onclick=()=>api()?.exportFilm();
 document.getElementById('realSingleExport').onclick=()=>api()?.exportSelected();
 document.getElementById('realAllExport').onclick=()=>api()?.exportClips();
 window.addEventListener('studio:viewjob',event=>{if(event.detail.type==='video')api()?.viewTask(event.detail.job_id)});
 // Keep both tabs mounted. Resize only when the video panel has a measurable width.
 new ResizeObserver(()=>{if(frame.clientWidth)api()?.fit()}).observe(frame);
})();
