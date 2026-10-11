"""FastAPI Application with Multi-Username, Drag-and-Drop Images, and Deep Image Forensics."""

import asyncio
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from config import PLATFORMS
from image_search import VisualSearchEngine
from username_recon import UsernameScanner

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Profile & Deep Visual Reconnaissance Studio")

# Serve uploaded images statically
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

SCAN_SESSIONS: Dict[str, Dict[str, Any]] = {}

HTML_CONTENT = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Profile & Deep Visual Reconnaissance Studio</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        .drag-active {
            border-color: #38bdf8 !important;
            background-color: rgba(14, 165, 233, 0.1) !important;
        }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen">
    <div class="max-w-7xl mx-auto px-4 py-8">
        
        <!-- Header -->
        <header class="mb-8 border-b border-slate-800 pb-6 flex flex-wrap items-center justify-between gap-4">
            <div>
                <h1 class="text-3xl font-black tracking-tight text-white flex items-center gap-3">
                    <i class="fa-solid fa-radar text-sky-400"></i> Profile & Deep Visual Recon Studio
                </h1>
                <p class="text-slate-400 text-sm mt-1">Validated public profile locator with deep image forensics & multi-engine visual matching</p>
            </div>
            <div class="flex items-center gap-3">
                <span id="badgeStatus" class="px-3 py-1 rounded-full text-xs font-semibold bg-slate-800 text-slate-300 border border-slate-700">
                    <i class="fa-solid fa-circle-dot text-emerald-400 mr-1"></i> Ready
                </span>
                <button id="downloadBtn" class="hidden px-4 py-2 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-sm font-semibold transition flex items-center gap-2 cursor-pointer">
                    <i class="fa-solid fa-download"></i> Export Results JSON
                </button>
            </div>
        </header>

        <!-- Main Input Form -->
        <form id="reconForm" class="bg-slate-900 border border-slate-800 rounded-2xl p-6 mb-8 shadow-2xl space-y-6">
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
                
                <!-- Target Usernames Area -->
                <div class="flex flex-col">
                    <div class="flex justify-between items-center mb-2">
                        <label class="text-xs font-bold uppercase tracking-wider text-slate-300">
                            <i class="fa-solid fa-users text-sky-400 mr-1.5"></i> Target Usernames
                        </label>
                        <span id="usernameCountBadge" class="text-xs bg-slate-800 px-2.5 py-0.5 rounded-full text-slate-400 border border-slate-700">0 usernames</span>
                    </div>
                    <textarea id="usernamesInput" rows="5" placeholder="Enter usernames separated by commas, spaces, or new lines...&#10;e.g.&#10;torvalds&#10;antirez, fabpot" 
                              class="w-full bg-slate-950 border border-slate-800 rounded-xl p-3.5 text-white placeholder-slate-600 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500 transition resize-none text-sm font-mono"></textarea>
                    <p class="text-xs text-slate-500 mt-2">
                        Verified with strict false-positive filtering across GitHub, GitLab, TikTok, Medium, Pinterest, Telegram, Keybase, Mastodon, etc.
                    </p>
                </div>

                <!-- Drag & Drop Images (Up to 10) -->
                <div class="flex flex-col">
                    <div class="flex justify-between items-center mb-2">
                        <label class="text-xs font-bold uppercase tracking-wider text-slate-300">
                            <i class="fa-solid fa-images text-indigo-400 mr-1.5"></i> Deep Image Forensics & Reverse Search
                        </label>
                        <span id="imageCountBadge" class="text-xs bg-slate-800 px-2.5 py-0.5 rounded-full text-slate-400 border border-slate-700">0 / 10 images</span>
                    </div>
                    
                    <!-- Drop Zone -->
                    <div id="dropZone" class="border-2 border-dashed border-slate-700 hover:border-slate-500 bg-slate-950/60 rounded-xl p-4 text-center cursor-pointer transition flex flex-col items-center justify-center min-h-[125px] relative">
                        <input type="file" id="fileInput" multiple accept="image/*" class="hidden">
                        <i class="fa-solid fa-cloud-arrow-up text-3xl text-slate-500 mb-2"></i>
                        <p class="text-sm font-medium text-slate-300">Drag & drop profile/face photos here, or <span class="text-sky-400 underline">browse</span></p>
                        <p class="text-xs text-slate-500 mt-1">Supports PNG, JPG, JPEG, WEBP, GIF (Max 10 files)</p>
                    </div>

                    <!-- Thumbnails Preview Grid -->
                    <div id="previewGrid" class="grid grid-cols-5 gap-2 mt-3 max-h-36 overflow-y-auto pr-1"></div>
                </div>

            </div>

            <!-- Submit Row -->
            <div class="flex justify-end pt-2 border-t border-slate-800">
                <button type="submit" id="submitBtn" class="px-6 py-3 bg-sky-600 hover:bg-sky-500 text-white font-bold rounded-xl transition flex items-center gap-2 shadow-lg shadow-sky-950 cursor-pointer">
                    <i class="fa-solid fa-play"></i> Launch Reconnaissance Scan
                </button>
            </div>
        </form>

        <!-- Progress Tracker -->
        <div id="progressSection" class="hidden mb-8 bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
            <div class="flex justify-between items-center text-sm mb-2">
                <span id="statusText" class="text-slate-300 font-medium flex items-center gap-2">
                    <i class="fa-solid fa-spinner fa-spin text-sky-400"></i> Scanning...
                </span>
                <span id="percentText" class="text-sky-400 font-bold">0%</span>
            </div>
            <div class="w-full bg-slate-950 rounded-full h-3 overflow-hidden border border-slate-800">
                <div id="progressBar" class="bg-gradient-to-r from-sky-500 to-indigo-500 h-3 rounded-full transition-all duration-300 w-0"></div>
            </div>
        </div>

        <!-- Results Section -->
        <div class="grid grid-cols-1 lg:grid-cols-12 gap-8">
            
            <!-- Left 6 Cols: Profiles Discovered -->
            <div class="lg:col-span-6 space-y-4">
                <div class="flex items-center justify-between">
                    <h2 class="text-lg font-bold text-white flex items-center gap-2">
                        <i class="fa-solid fa-id-badge text-emerald-400"></i> Verified Public Profiles
                    </h2>
                    <span id="totalProfilesFound" class="text-xs bg-emerald-950 border border-emerald-800 text-emerald-300 px-2.5 py-0.5 rounded-full font-bold">0 Matches</span>
                </div>
                
                <div id="profilesContainer" class="space-y-4">
                    <div class="p-8 text-center text-slate-500 bg-slate-900/50 border border-slate-800/80 rounded-xl">
                        <i class="fa-solid fa-magnifying-glass text-3xl mb-3 text-slate-600 block"></i>
                        No active scan. Enter usernames or drop images above to begin.
                    </div>
                </div>
            </div>

            <!-- Right 6 Cols: Deep Visual Intelligence & Live Feed -->
            <div class="lg:col-span-6 space-y-6">
                
                <!-- Visual Matches -->
                <div>
                    <div class="flex items-center justify-between mb-4">
                        <h2 class="text-lg font-bold text-white flex items-center gap-2">
                            <i class="fa-solid fa-magnifying-glass-location text-amber-400"></i> Deep Visual Forensics & Matches
                        </h2>
                        <span id="totalVisualMatches" class="text-xs bg-amber-950 border border-amber-800 text-amber-300 px-2.5 py-0.5 rounded-full font-bold">0 Analyzed</span>
                    </div>
                    <div id="visualContainer" class="space-y-4">
                        <div class="p-6 text-center text-slate-500 bg-slate-900/50 border border-slate-800/80 rounded-xl text-xs">
                            Drop images to see EXIF forensics, dHash fingerprints, GPS mapping, and reverse image matching.
                        </div>
                    </div>
                </div>

                <!-- Live Stream Feed -->
                <div>
                    <h2 class="text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">Live Stream Activity</h2>
                    <div id="eventStream" class="h-44 overflow-y-auto bg-slate-950 border border-slate-800 rounded-xl p-3.5 text-xs font-mono space-y-1">
                        <div class="text-slate-600">// Ready for instructions...</div>
                    </div>
                </div>

            </div>

        </div>

    </div>

    <script>
        const form = document.getElementById('reconForm');
        const usernamesInput = document.getElementById('usernamesInput');
        const usernameCountBadge = document.getElementById('usernameCountBadge');
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        const previewGrid = document.getElementById('previewGrid');
        const imageCountBadge = document.getElementById('imageCountBadge');
        const submitBtn = document.getElementById('submitBtn');
        const progressSection = document.getElementById('progressSection');
        const progressBar = document.getElementById('progressBar');
        const percentText = document.getElementById('percentText');
        const statusText = document.getElementById('statusText');
        const badgeStatus = document.getElementById('badgeStatus');
        const profilesContainer = document.getElementById('profilesContainer');
        const visualContainer = document.getElementById('visualContainer');
        const totalProfilesFound = document.getElementById('totalProfilesFound');
        const totalVisualMatches = document.getElementById('totalVisualMatches');
        const eventStream = document.getElementById('eventStream');
        const downloadBtn = document.getElementById('downloadBtn');

        let selectedFiles = [];
        let finalResultsData = { usernames: {}, visual: [] };
        let currentEventSource = null;

        function getParsedUsernames() {
            const raw = usernamesInput.value;
            const matches = raw.split(/[\s,;]+/).map(u => u.replace(/^@/, '').trim()).filter(Boolean);
            return [...new Set(matches)];
        }

        usernamesInput.addEventListener('input', () => {
            const list = getParsedUsernames();
            usernameCountBadge.innerText = `${list.length} username${list.length === 1 ? '' : 's'}`;
        });

        dropZone.addEventListener('click', () => fileInput.click());

        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.classList.add('drag-active');
            });
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.classList.remove('drag-active');
            });
        });

        dropZone.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const files = Array.from(dt.files).filter(f => f.type.startsWith('image/'));
            addFiles(files);
        });

        fileInput.addEventListener('change', (e) => {
            const files = Array.from(e.target.files);
            addFiles(files);
            fileInput.value = '';
        });

        function addFiles(newFiles) {
            const total = selectedFiles.length + newFiles.length;
            if (total > 10) {
                alert(`Maximum 10 images allowed.`);
            }
            for (const f of newFiles) {
                if (selectedFiles.length >= 10) break;
                if (!selectedFiles.some(existing => existing.name === f.name && existing.size === f.size)) {
                    selectedFiles.push(f);
                }
            }
            renderPreviews();
        }

        function removeFile(index) {
            selectedFiles.splice(index, 1);
            renderPreviews();
        }

        function renderPreviews() {
            previewGrid.innerHTML = '';
            imageCountBadge.innerText = `${selectedFiles.length} / 10 images`;
            selectedFiles.forEach((file, index) => {
                const reader = new FileReader();
                const card = document.createElement('div');
                card.className = "relative group bg-slate-900 border border-slate-800 rounded-lg overflow-hidden h-16 w-full";
                
                reader.onload = (e) => {
                    card.innerHTML = `
                        <img src="${e.target.result}" class="h-full w-full object-cover">
                        <button type="button" onclick="removeFile(${index})" class="absolute top-1 right-1 bg-rose-600 hover:bg-rose-500 text-white rounded-full h-4 w-4 flex items-center justify-center text-[10px] opacity-90 group-hover:opacity-100 transition shadow">
                            &times;
                        </button>
                    `;
                };
                reader.readAsDataURL(file);
                previewGrid.appendChild(card);
            });
        }

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const usernames = getParsedUsernames();

            if (usernames.length === 0 && selectedFiles.length === 0) {
                alert('Please enter at least one username or upload an image.');
                return;
            }

            if (currentEventSource) {
                currentEventSource.close();
            }

            profilesContainer.innerHTML = '';
            visualContainer.innerHTML = '';
            eventStream.innerHTML = '';
            totalProfilesFound.innerText = '0 Matches';
            totalVisualMatches.innerText = '0 Analyzed';
            downloadBtn.classList.add('hidden');
            progressSection.classList.remove('hidden');
            progressBar.style.width = '0%';
            percentText.innerText = '0%';
            statusText.innerHTML = '<i class="fa-solid fa-spinner fa-spin text-sky-400"></i> Initializing scan session...';
            submitBtn.disabled = true;
            submitBtn.classList.add('opacity-50');
            badgeStatus.innerHTML = '<i class="fa-solid fa-circle-dot text-amber-400 mr-1"></i> Running';

            finalResultsData = { usernames: {}, visual: [] };

            usernames.forEach(user => {
                finalResultsData.usernames[user] = [];
                const userBox = document.createElement('div');
                userBox.id = `user-section-${user}`;
                userBox.className = "bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3";
                userBox.innerHTML = `
                    <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                        <span class="font-bold text-white text-sm flex items-center gap-2">
                            <i class="fa-solid fa-user-tag text-sky-400"></i> @${user}
                        </span>
                        <span id="badge-count-${user}" class="text-xs bg-slate-800 text-slate-400 px-2 py-0.5 rounded-full font-mono">0 verified</span>
                    </div>
                    <div id="links-container-${user}" class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        <div class="text-slate-600 text-xs italic col-span-2">Verifying platforms...</div>
                    </div>
                `;
                profilesContainer.appendChild(userBox);
            });

            const formData = new FormData();
            formData.append('usernames', usernames.join(','));
            selectedFiles.forEach(file => {
                formData.append('images', file);
            });

            try {
                const res = await fetch('/api/scan', {
                    method: 'POST',
                    body: formData,
                });

                if (!res.ok) throw new Error(`HTTP Error ${res.status}`);

                const initData = await res.json();
                const sessionId = initData.session_id;

                currentEventSource = new EventSource(`/api/stream/${sessionId}`);

                currentEventSource.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    
                    if (data.type === 'log') {
                        const logEl = document.createElement('div');
                        logEl.className = data.found ? 'text-emerald-400 font-bold' : 'text-slate-500';
                        logEl.innerText = `[${new Date().toLocaleTimeString()}] @${data.username} on ${data.platform}: ${data.found ? 'VERIFIED' : '404'}`;
                        eventStream.prepend(logEl);

                        const pct = Math.round((data.checked_ops / data.total_ops) * 90);
                        progressBar.style.width = `${pct}%`;
                        percentText.innerText = `${pct}%`;
                        statusText.innerHTML = `<i class="fa-solid fa-spinner fa-spin text-sky-400"></i> @${data.username} checking ${data.platform}...`;

                        if (data.found) {
                            finalResultsData.usernames[data.username].push({ platform: data.platform, url: data.url });
                            
                            const userCountEl = document.getElementById(`badge-count-${data.username}`);
                            if (userCountEl) {
                                userCountEl.innerText = `${finalResultsData.usernames[data.username].length} verified`;
                                userCountEl.className = "text-xs bg-emerald-950 text-emerald-300 border border-emerald-800 px-2 py-0.5 rounded-full font-mono";
                            }

                            const linksBox = document.getElementById(`links-container-${data.username}`);
                            if (linksBox) {
                                if (linksBox.querySelector('.text-slate-600')) {
                                    linksBox.innerHTML = '';
                                }
                                const item = document.createElement('a');
                                item.href = data.url;
                                item.target = "_blank";
                                item.className = "bg-slate-950 border border-slate-800 hover:border-emerald-500/60 p-2.5 rounded-lg flex items-center justify-between transition group";
                                item.innerHTML = `
                                    <span class="text-xs font-semibold text-slate-200">${data.platform}</span>
                                    <i class="fa-solid fa-arrow-up-right-from-square text-[10px] text-slate-500 group-hover:text-emerald-400"></i>
                                `;
                                linksBox.appendChild(item);
                            }

                            const sum = Object.values(finalResultsData.usernames).reduce((acc, arr) => acc + arr.length, 0);
                            totalProfilesFound.innerText = `${sum} Matches`;
                        }
                    }
                    else if (data.type === 'image_start') {
                        statusText.innerHTML = `<i class="fa-solid fa-spinner fa-spin text-amber-400"></i> Extracting deep forensics for ${data.filename}...`;
                    }
                    else if (data.type === 'image_result') {
                        finalResultsData.visual.push(data);
                        
                        const vCard = document.createElement('div');
                        vCard.className = "bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-4 shadow-lg";
                        
                        const fn = data.forensics || {};
                        const exif = fn.exif || {};
                        const gps = fn.gps;

                        // Build EXIF Summary
                        let exifDetails = [];
                        if (exif.Make || exif.Model) exifDetails.push(`Camera: ${exif.Make || ''} ${exif.Model || ''}`);
                        if (exif.DateTime || exif.DateTimeOriginal) exifDetails.push(`Date: ${exif.DateTime || exif.DateTimeOriginal}`);
                        if (exif.Software) exifDetails.push(`Software: ${exif.Software}`);

                        const exifHtml = exifDetails.length > 0
                            ? `<div class="text-[11px] text-slate-400 bg-slate-950 p-2 rounded border border-slate-800 font-mono space-y-0.5">${exifDetails.map(d => `<div>• ${d}</div>`).join('')}</div>`
                            : `<div class="text-[11px] text-slate-500 italic">No camera/software EXIF tags embedded.</div>`;

                        // GPS Map Button
                        const gpsHtml = gps ? `
                            <a href="${gps.maps_url}" target="_blank" class="inline-flex items-center gap-1.5 px-2.5 py-1 bg-emerald-950 border border-emerald-800 text-emerald-300 text-[11px] rounded-lg font-semibold hover:bg-emerald-900 transition">
                                <i class="fa-solid fa-location-dot"></i> GPS: ${gps.latitude}, ${gps.longitude} (Open Map)
                            </a>
                        ` : '';

                        // Multi-Engine Search Buttons
                        const engineLinks = data.engine_links || {};
                        const buttonsHtml = `
                            <div class="pt-2 border-t border-slate-800">
                                <div class="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-2">Deep Web Reverse Search:</div>
                                <div class="flex flex-wrap gap-2">
                                    <a href="${engineLinks.google_lens || 'https://lens.google.com/'}" target="_blank" class="px-2.5 py-1.5 bg-slate-950 border border-slate-700 hover:border-sky-400 rounded text-[11px] font-semibold text-sky-300 flex items-center gap-1.5 transition">
                                        <i class="fa-brands fa-google text-sky-400"></i> Google Lens
                                    </a>
                                    <a href="${engineLinks.yandex || 'https://yandex.com/images/'}" target="_blank" class="px-2.5 py-1.5 bg-slate-950 border border-slate-700 hover:border-amber-400 rounded text-[11px] font-semibold text-amber-300 flex items-center gap-1.5 transition">
                                        <i class="fa-brands fa-yandex text-amber-400"></i> Yandex Visual
                                    </a>
                                    <a href="${engineLinks.bing || 'https://www.bing.com/visualsearch'}" target="_blank" class="px-2.5 py-1.5 bg-slate-950 border border-slate-700 hover:border-blue-400 rounded text-[11px] font-semibold text-blue-300 flex items-center gap-1.5 transition">
                                        <i class="fa-brands fa-microsoft text-blue-400"></i> Bing Visual
                                    </a>
                                    <a href="${engineLinks.tineye || 'https://tineye.com/'}" target="_blank" class="px-2.5 py-1.5 bg-slate-950 border border-slate-700 hover:border-purple-400 rounded text-[11px] font-semibold text-purple-300 flex items-center gap-1.5 transition">
                                        <i class="fa-solid fa-fingerprint text-purple-400"></i> TinEye
                                    </a>
                                </div>
                            </div>
                        `;

                        // Match Results
                        let matchesHtml = '';
                        if (data.matches && data.matches.length > 0) {
                            matchesHtml = `
                                <div class="space-y-1.5 pt-2 border-t border-slate-800">
                                    <div class="text-[11px] font-bold uppercase text-emerald-400">API Matches Found:</div>
                                    ${data.matches.map(m => `
                                        <div class="p-2 bg-slate-950 rounded border border-slate-800 text-xs">
                                            <div class="font-bold text-sky-300 truncate">${m.title || 'Visual Match'}</div>
                                            <a href="${m.url}" target="_blank" class="text-slate-400 hover:underline truncate block text-[11px] mt-0.5">${m.url}</a>
                                        </div>
                                    `).join('')}
                                </div>
                            `;
                        } else if (data.notice) {
                            matchesHtml = `<p class="text-slate-400 text-xs italic bg-slate-950 p-2.5 rounded border border-slate-800">${data.notice}</p>`;
                        }

                        vCard.innerHTML = `
                            <div class="flex items-start gap-3">
                                <img src="${data.file_url}" class="h-16 w-16 rounded-lg object-cover border border-slate-700 shadow-md">
                                <div class="space-y-1">
                                    <div class="font-bold text-white text-xs truncate max-w-sm">${data.filename}</div>
                                    <div class="text-[11px] text-slate-400">
                                        ${fn.width || 0}x${fn.height || 0} (${fn.format || 'IMG'}, ${fn.color_mode || 'RGB'}) • ${fn.file_size_kb || 0} KB
                                    </div>
                                    <div class="text-[10px] text-slate-500 font-mono">dHash: ${fn.dhash || 'N/A'}</div>
                                </div>
                            </div>
                            ${gpsHtml}
                            ${exifHtml}
                            ${buttonsHtml}
                            ${matchesHtml}
                        `;

                        if (visualContainer.querySelector('.text-center')) {
                            visualContainer.innerHTML = '';
                        }
                        visualContainer.appendChild(vCard);

                        totalVisualMatches.innerText = `${finalResultsData.visual.length} Analyzed`;
                    }
                    else if (data.type === 'complete') {
                        progressBar.style.width = '100%';
                        percentText.innerText = '100%';
                        statusText.innerHTML = '<i class="fa-solid fa-check text-emerald-400"></i> Scan complete!';
                        badgeStatus.innerHTML = '<i class="fa-solid fa-circle-dot text-emerald-400 mr-1"></i> Completed';
                        submitBtn.disabled = false;
                        submitBtn.classList.remove('opacity-50');
                        downloadBtn.classList.remove('hidden');
                        currentEventSource.close();
                    }
                };

                currentEventSource.onerror = () => {
                    statusText.innerHTML = '<i class="fa-solid fa-check text-emerald-400"></i> Completed.';
                    submitBtn.disabled = false;
                    submitBtn.classList.remove('opacity-50');
                    if (currentEventSource) currentEventSource.close();
                };

            } catch (err) {
                alert(`Error: ${err.message}`);
                submitBtn.disabled = false;
                submitBtn.classList.remove('opacity-50');
            }
        });

        downloadBtn.addEventListener('click', () => {
            const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(finalResultsData, null, 2));
            const dlAnchor = document.createElement('a');
            dlAnchor.setAttribute("href", dataStr);
            dlAnchor.setAttribute("download", `recon_report_${Date.now()}.json`);
            document.body.appendChild(dlAnchor);
            dlAnchor.click();
            dlAnchor.remove();
        });
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def get_index():
    return HTMLResponse(content=HTML_CONTENT)


@app.post("/api/scan")
async def start_scan(
    usernames: str = Form(""),
    images: List[UploadFile] = File([]),
):
    tokens = re.split(r"[\s,;]+", usernames)
    cleaned_usernames = [t.lstrip("@").strip() for t in tokens if t.strip()]
    unique_usernames = list(dict.fromkeys(cleaned_usernames))

    saved_images: List[Dict[str, str]] = []
    for upload in images[:10]:
        if not upload.filename:
            continue
        safe_name = f"{uuid.uuid4().hex[:8]}_{Path(upload.filename).name}"
        dest_path = UPLOAD_DIR / safe_name
        contents = await upload.read()
        with open(dest_path, "wb") as f:
            f.write(contents)

        saved_images.append({
            "filename": upload.filename,
            "filepath": str(dest_path),
            "file_url": f"/uploads/{safe_name}",
        })

    session_id = uuid.uuid4().hex
    SCAN_SESSIONS[session_id] = {
        "usernames": unique_usernames,
        "images": saved_images,
    }

    return {
        "session_id": session_id,
        "usernames_count": len(unique_usernames),
        "images_count": len(saved_images),
    }


@app.get("/api/stream/{session_id}")
async def stream_scan_progress(session_id: str):
    session = SCAN_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    target_usernames: List[str] = session["usernames"]
    target_images: List[Dict[str, str]] = session["images"]

    total_ops = (len(target_usernames) * len(PLATFORMS)) + len(target_images)
    total_ops = max(total_ops, 1)

    async def event_generator() -> AsyncGenerator[str, None]:
        checked_ops = 0
        scanner = UsernameScanner(max_concurrency=4)
        engine = VisualSearchEngine()

        # 1. Process all usernames
        for user in target_usernames:
            async for check in scanner.stream_scan(user):
                checked_ops += 1
                payload = {
                    "type": "log",
                    "username": user,
                    "platform": check["platform"],
                    "url": check["url"],
                    "found": check["found"],
                    "checked_ops": checked_ops,
                    "total_ops": total_ops,
                }
                yield f"data: {json.dumps(payload)}\n\n"

        # 2. Process all uploaded images with deep forensics
        for img in target_images:
            yield f"data: {json.dumps({'type': 'image_start', 'filename': img['filename']})}\n\n"

            res = await engine.search_by_file(img["filepath"])
            checked_ops += 1

            payload = {
                "type": "image_result",
                "filename": img["filename"],
                "file_url": img["file_url"],
                "forensics": res.get("forensics", {}),
                "engine_links": res.get("engine_links", {}),
                "matches": res.get("matches", []),
                "notice": res.get("notice") or res.get("error"),
                "checked_ops": checked_ops,
                "total_ops": total_ops,
            }
            yield f"data: {json.dumps(payload)}\n\n"

        # 3. Completion signal
        yield f"data: {json.dumps({'type': 'complete'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
