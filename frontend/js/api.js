import { API_BASE } from './state.js';

export async function fetchManifest(bookId) {
    const res = await fetch(`${API_BASE}/books/${bookId}/manifest`);
    if (!res.ok) throw new Error('Failed to load manifest');
    return await res.json();
}

export async function fetchChunk(bookId, fileName) {
    const res = await fetch(`${API_BASE}/books/${bookId}/chunk/${fileName}`);
    if (!res.ok) throw new Error('Failed to load chunk');
    return await res.json();
}

export async function fetchAnnotations(bookId) {
    const res = await fetch(`${API_BASE}/books/${bookId}/annotations`);
    if (res.ok) return await res.json();
    return [];
}

export async function saveAnnotation(bookId, data) {
    const res = await fetch(`${API_BASE}/books/${bookId}/annotations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    return res;
}
