const chapterConfig = [
    {
        number: 1,
        title: "The Need for Innovation in US Higher Education",
        file: "abstracts/chapter1.abstract.txt"
    },
    {
        number: 2,
        title: "Adapting to the Financial Realities of Higher Education: Balancing Tradition and Change",
        file: "abstracts/chapter2.abstract.txt"
    },
    {
        number: 3,
        title: "Entrepreneurial Cultures and Lessons for Higher Education",
        file: "abstracts/chapter3.abstract.txt"
    },
    {
        number: 4,
        title: "The Emergence of New Universities in the 21st Century",
        file: "abstracts/chapter4.abstract.txt"
    },
    {
        number: 5,
        title: "Teaching Innovation at the Top R1 Universities",
        file: "abstracts/chapter5.abstract.txt"
    },
    {
        number: 6,
        title: "Rapidly Growing Universities",
        file: "abstracts/chapter6.abstract.txt"
    },
    {
        number: 7,
        title: "AI Goes to College: Higher Education in the Age of AI",
        file: "abstracts/chapter7.abstract.txt"
    },
    {
        number: 8,
        title: "Reimagining the Residential University",
        file: "abstracts/chapter8.abstract.txt"
    },
    {
        number: 9,
        title: "Making the Future-Proof University",
        file: "abstracts/chapter9.abstract.txt"
    }
];

async function loadAbstract(filePath) {
    const response = await fetch(filePath, { cache: "no-store" });
    if (!response.ok) {
        throw new Error(`Failed to load ${filePath}`);
    }

    const buffer = await response.arrayBuffer();

    const utf8Text = new TextDecoder("utf-8", { fatal: false }).decode(buffer);
    if (!utf8Text.includes("�")) {
        return normalizeAbstractText(utf8Text);
    }

    const win1252Text = new TextDecoder("windows-1252", { fatal: false }).decode(buffer);
    return normalizeAbstractText(win1252Text);
}

function normalizeAbstractText(text) {
    return text
    .replace(/\s\uFFFD\s/g, " — ")
        .replace(/\uFFFD/g, "-")
        .replace(/\r\n/g, "\n")
        .replace(/\r/g, "\n");
}

async function loadChapters() {
    return Promise.all(
        chapterConfig.map(async (chapter) => {
            const abstract = await loadAbstract(chapter.file);
            return {
                ...chapter,
                abstract
            };
        })
    );
}

// Get excerpt of abstract (first 200 characters)
function getExcerpt(text, length = 200) {
    if (text.length <= length) return text;
    return text.substring(0, length) + '...';
}

// Populate chapters on page load
document.addEventListener('DOMContentLoaded', async function() {
    const chaptersContainer = document.querySelector('.chapters-grid');

    let chapters = [];
    try {
        chapters = await loadChapters();
    } catch (error) {
        chaptersContainer.innerHTML = '<p>Unable to load chapter abstracts right now. Please refresh the page.</p>';
        return;
    }

    chapters.forEach(chapter => {
        const chapterCard = document.createElement('div');
        chapterCard.className = 'chapter-card';
        const excerpt = getExcerpt(chapter.abstract, 200);
        
        chapterCard.innerHTML = `
            <div class="chapter-header">
                <span class="chapter-number">Chapter ${chapter.number}</span>
                <h3 class="chapter-title">${chapter.title}<span class="expand-icon">▼</span></h3>
            </div>
            <div class="chapter-body">
                <p class="chapter-abstract">
                    <span class="abstract-excerpt"></span>
                    <span class="abstract-full" style="display:none;"></span>
                    <a href="#" class="read-more-link"> Read More</a>
                </p>
            </div>
        `;

        const excerptElement = chapterCard.querySelector('.abstract-excerpt');
        const fullElement = chapterCard.querySelector('.abstract-full');
        excerptElement.textContent = excerpt;
        fullElement.textContent = chapter.abstract;

        const readMoreLink = chapterCard.querySelector('.read-more-link');
        if (chapter.abstract.length <= 200) {
            readMoreLink.style.display = 'none';
        }
        
        // Handle chapter card expand/collapse
        chapterCard.addEventListener('click', function(e) {
            // Don't toggle if clicking the read more link
            if (e.target.classList.contains('read-more-link')) {
                return;
            }
            this.classList.toggle('active');
        });
        
        // Handle read more link
        readMoreLink.addEventListener('click', function(e) {
            e.preventDefault();
            const excerpt = this.parentElement.querySelector('.abstract-excerpt');
            const full = this.parentElement.querySelector('.abstract-full');
            
            if (full.style.display === 'none') {
                excerpt.style.display = 'none';
                full.style.display = 'inline';
                this.textContent = ' Read Less';
                // Expand the card if not already
                chapterCard.classList.add('active');
            } else {
                excerpt.style.display = 'inline';
                full.style.display = 'none';
                this.textContent = ' Read More';
            }
        });
        
        chaptersContainer.appendChild(chapterCard);
    });

    // Smooth scrolling for navigation links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({ behavior: 'smooth' });
            }
        });
    });
});
