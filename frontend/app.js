const API_BASE = '/api';
let currentPage = 0;
const limit = 50;
let currentSearch = '';
let currentDownloadedOnly = false;

const searchView = document.getElementById('search-view');
const bookList = document.getElementById('book-list');
const searchInput = document.getElementById('search-input');
const dlOnlyCheckbox = document.getElementById('downloaded-only');
const searchButton = document.getElementById('search-button');
const prevPageBtn = document.getElementById('prev-page');
const nextPageBtn = document.getElementById('next-page');
const pageInfo = document.getElementById('page-info');

searchButton.addEventListener('click', () => {
    currentPage = 0;
    currentSearch = searchInput.value.trim();
    currentDownloadedOnly = dlOnlyCheckbox.checked;
    fetchBooks();
});

searchInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') searchButton.click();
});

prevPageBtn.addEventListener('click', () => {
    if (currentPage > 0) {
        currentPage--;
        fetchBooks();
    }
});

nextPageBtn.addEventListener('click', () => {
    currentPage++;
    fetchBooks();
});



async function fetchBooks() {
    bookList.innerHTML = '<div style="text-align:center;grid-column:1/-1;">読み込み中...</div>';
    
    const offset = currentPage * limit;
    let url = `${API_BASE}/books?limit=${limit}&offset=${offset}`;
    if (currentSearch) url += `&search=${encodeURIComponent(currentSearch)}`;
    if (currentDownloadedOnly) url += `&downloaded_only=true`;

    try {
        const res = await fetch(url);
        const data = await res.json();
        renderBooks(data.books, data.total);
    } catch (err) {
        console.error(err);
        bookList.innerHTML = '<div style="text-align:center;grid-column:1/-1;">エラーが発生しました。</div>';
    }
}

function renderBooks(books, total) {
    bookList.innerHTML = '';
    
    if (books.length === 0) {
        bookList.innerHTML = '<div style="text-align:center;grid-column:1/-1;">本が見つかりませんでした。</div>';
        pageInfo.textContent = `0 / 0 件`;
        prevPageBtn.disabled = true;
        nextPageBtn.disabled = true;
        return;
    }

    books.forEach(book => {
        const card = document.createElement('div');
        card.className = 'book-card';
        
        const isReady = book.is_downloaded_actual;
        
        card.innerHTML = `
            <div class="book-title">${escapeHTML(book.title)}</div>
            <div class="book-author">${escapeHTML(book.author || '')}</div>
            <div class="book-status ${isReady ? 'status-downloaded' : 'status-not-downloaded'}">
                ${isReady ? '✓ すぐ読めます' : 'ダウンロード未済'}
            </div>
        `;
        
        card.addEventListener('click', () => {
            if (isReady) {
                openReader(book.id, book.title);
            } else {
                alert('この作品のテキストはまだダウンロードされていません。');
            }
        });
        
        bookList.appendChild(card);
    });

    const start = currentPage * limit + 1;
    const end = Math.min((currentPage + 1) * limit, total);
    pageInfo.textContent = `${start} - ${end} / ${total} 件`;
    
    prevPageBtn.disabled = currentPage === 0;
    nextPageBtn.disabled = end >= total;
}

function openReader(bookId, title) {
    // 読書画面へのページ遷移 (MPAアーキテクチャ)
    window.location.href = `viewer.html?id=${bookId}`;
}

function escapeHTML(str) {
    if (!str) return '';
    return str.replace(/[&<>'"]/g, 
        tag => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            "'": '&#39;',
            '"': '&quot;'
        }[tag] || tag)
    );
}

// 初期データの読み込み
fetchBooks();
