// Contributors data
const contributors = [
    { name: "Bryan Penprase", title: "Vice President of Sponsored Research and External Academic Relations, Soka University of America" },
    { name: "Kyle Farley", title: "Partner, Cross Borders Education" },
    { name: "Sara Pervaiz Amjad", title: "Associate Dean of Student Affairs at New York University Abu Dhabi" },
    { name: "Jeff Lehman", title: "Vice Chancellor of NYU Shanghai" },
    { name: "Noah Pickus", title: "Head of Global Strategy and Partnerships, Duke University (Duke Kunshan University)" },
    { name: "Pericles Lewis", title: "Dean of the College, Yale University / inaugural President, Yale-NUS College" },
    { name: "Joanne Roberts", title: "Vice President for Academic Affairs and Dean of the College, Bates College (formerly President, Yale-NUS College)" },
    { name: "Dave Stanfield", title: "Vice President of Student Affairs and Dean of Students, Sarah Lawrence College (formerly Dean of Students, Yale-NUS College)" },
    { name: "Al Bloom", title: "Swarthmore, NYU Abu Dhabi, Duke Kunshan University" },
    { name: "Fatiah Touray", title: "Assistant Vice Chancellor, Global Access and Engagement, NYU" },
    { name: "Zhana Sandeva", title: "Associate Director, NUS (formerly at Yale-NUS College)" },
    { name: "Bryan Waterman", title: "Associate Professor of English, NYU, (formerly at NYU Abu Dhabi)" },
    { name: "Kaashif Hajee", title: "NYUAD alum" },
    { name: "Aisha Al Naqbi", title: "Senior Dean of Students, NYUAD" },
    { name: "Melanie Koenderman", title: "Partner, Cross Borders Education (formerly with Quest University, Schwarzman Scholars Program)" },
    { name: "Ryan Derby-Talbot", title: "inaugural President, Experiential College of the UAE (formerly with Fulbright Vietnam and Quest University Canada)" },
    { name: "Khoo Hoon Eng", title: "Emeritus Professor, NUS (formerly with Asian University for Women, Yale-NUS College, Asian Women’s Leadership University College)" },
    { name: "Catherine Shea Sanger", title: "Intentional Education Consulting (formerly with Yale-NUS College)" },
    { name: "Thais Thomas", title: "NYU Office of Social Responsibility (NYUAD alum)" }
];

// Chapter data organized by parts
// Complete chapter information for the book
const chaptersByPart = {
    1: [
        {
            number: 2,
            title: "The History and Evolution of Global Universities",
            authors: "Bryan Penprase, Kyle Farley and Sara Pervaiz Amjad"
        },
        {
            number: 3,
            title: "\"Don't Burn the Last Bridge\": The Special Duty of Universities When Nations Start To Decouple",
            authors: "Jeff Lehman (NYU Shanghai)"
        },
        {
            number: 4,
            title: "Rooted Globalism and Its Discontents",
            authors: "Noah Pickus (DKU)"
        },
        {
            number: 5,
            title: "Educating Global Citizens in Singapore and New Haven",
            authors: "Pericles Lewis (Yale-NUS)"
        },
        {
            number: 6,
            title: "Settling In: Balancing Global Aspirations with Local Realities in the Next Generation of Campus Leadership",
            authors: "Joanne Roberts and Dave Stanfield (Yale-NUS)"
        },
        {
            number: 7,
            title: "Bridging Divides: Higher Education's Role in a Fractured World",
            authors: "Al Bloom (Swarthmore, NYU Abu Dhabi, Duke Kunshan)"
        }
    ],
    2: [
        {
            number: 8,
            title: "Creating a Global Curriculum and an Inclusive Multicultural Classroom",
            authors: "Sara Pervaiz Amjad, Bryan Penprase, and Kyle Farley"
        },
        {
            number: 9,
            title: "Bridging Pedagogy and Inclusion in Global Higher Education",
            authors: "Nancy Gleason (NYUAD + Yale-NUS) and Fatiah Touray (NYU-AD)"
        },
        {
            number: 10,
            title: "Undergraduate Research for a Global Student Body",
            authors: "Zhana Zendhaya (Yale-NUS)"
        },
        {
            number: 11,
            title: "Hacking the Core at NYU Abu Dhabi",
            authors: "Bryan Waterman (NYUAD)"
        },
        {
            number: 12,
            title: "Unwrapping the Global University: Inclusion, Exclusion, and the Search for Meaning",
            authors: "Kaashif Hajee (NYUAD alum, India)"
        },
        {
            number: 13,
            title: "Minerva University: Reimagining Education in the Global Era",
            authors: "Martina Mikulan (Otto-Benecke-Stiftung) and Jason Lindo (Minerva University)"
        }
    ],
    3: [
        {
            number: 14,
            title: "Building Community Across Cultures and Managing Residential Life in an International Context",
            authors: "Kyle Farley, Sara Pervaiz Amjad, and Bryan Penprase"
        },
        {
            number: 15,
            title: "Cultivate Belonging: Fostering Connection in Global (and Local) Campus Environments",
            authors: "Kyle Farley (Yale-NUS + NYUAD)"
        },
        {
            number: 16,
            title: "Navigating Multicultural Understandings of an Intercultural Student Community",
            authors: "Sara PervaizAmjad (Yale-NUS + NYUAD)"
        },
        {
            number: 17,
            title: "Cultural Sensitivity and Global Ambition: A UAE Perspective on International Higher Education",
            authors: "Aisha Al-Naqbi (NYUAD)"
        },
        {
            number: 18,
            title: "Creating International Campus Communities",
            authors: "Melanie Koenderman (Quest/Schwartzman) and Ryan Derby-Talbot (Quest, Fulbright Vietnam)"
        },
        {
            number: 19,
            title: "Intercultural Pedagogy and the Global University",
            authors: "Kate Sanger (Yale-NUS) and Hoon Eng Khoo (Yale-NUS, Asian University for Women)"
        },
        {
            number: 20,
            title: "Assume Goodwill? Balancing Ideals and Reality at a Global University",
            authors: "Priya Thomas (NYUAD)"
        }
    ]
};

// Toggle part expand/collapse
function togglePart(partNumber) {
    const partPanel = document.getElementById(`part-${partNumber}`);
    partPanel.classList.toggle('collapsed');
}

// Populate chapters on page load
document.addEventListener('DOMContentLoaded', function() {
    // Populate chapters for each part
    for (let partNum = 1; partNum <= 3; partNum++) {
        const chaptersGrid = document.getElementById(`chapters-part-${partNum}`);
        const chapters = chaptersByPart[partNum] || [];
        
        chapters.forEach(chapter => {
            const chapterCard = document.createElement('div');
            chapterCard.className = 'chapter-card';
            
            const numberCircle = document.createElement('div');
            numberCircle.className = 'chapter-number';
            numberCircle.textContent = chapter.number;
            
            const title = document.createElement('h3');
            title.className = 'chapter-title';
            title.textContent = chapter.title;
            
            const authors = document.createElement('p');
            authors.className = 'chapter-authors';
            authors.textContent = chapter.authors;
            
            chapterCard.appendChild(numberCircle);
            chapterCard.appendChild(title);
            chapterCard.appendChild(authors);
            
            chaptersGrid.appendChild(chapterCard);
        });
    }
    
    // Populate contributors
    const contributorsGrid = document.getElementById('contributors-grid');
    if (contributorsGrid) {
        contributors.forEach(contributor => {
            const contributorCard = document.createElement('div');
            contributorCard.className = 'contributor-card';
            
            const nameElement = document.createElement('h3');
            nameElement.className = 'contributor-name';
            nameElement.textContent = contributor.name;
            
            const titleElement = document.createElement('p');
            titleElement.className = 'contributor-title';
            titleElement.textContent = contributor.title;
            
            contributorCard.appendChild(nameElement);
            contributorCard.appendChild(titleElement);
            
            contributorsGrid.appendChild(contributorCard);
        });
    }
});

// Button event listeners
document.querySelectorAll('.btn').forEach(button => {
    button.addEventListener('click', function(e) {
        if (this.textContent === 'Learn More') {
            document.querySelector('#about').scrollIntoView({ behavior: 'smooth' });
        } else if (this.textContent === 'View Chapters') {
            document.querySelector('#chapters').scrollIntoView({ behavior: 'smooth' });
            // Expand all parts on first load
            const allParts = document.querySelectorAll('.part-panel');
            allParts.forEach(part => {
                part.classList.remove('collapsed');
            });
        }
    });
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

// Authors Page Authentication
const VALID_USERNAME = 'AHEAauthor';
const VALID_PASSWORD = 'AHEAauthor2026';

document.addEventListener('DOMContentLoaded', function() {
    // Check if user is authenticated when page loads
    const isAuthenticated = sessionStorage.getItem('authorsPageAuth') === 'true';
    if (isAuthenticated) {
        showAuthorsContent();
    }
    
    // Login form handler
    const loginForm = document.getElementById('login-form');
    if (loginForm) {
        loginForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            const errorDiv = document.getElementById('login-error');
            
            if (username === VALID_USERNAME && password === VALID_PASSWORD) {
                sessionStorage.setItem('authorsPageAuth', 'true');
                errorDiv.textContent = '';
                showAuthorsContent();
            } else {
                errorDiv.textContent = 'Invalid username or password. Please try again.';
            }
        });
    }
    
    // Logout button handler
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', function() {
            sessionStorage.removeItem('authorsPageAuth');
            document.getElementById('login-form').reset();
            showAuthsContainer();
        });
    }
    
    // File upload form handler
    const uploadForm = document.getElementById('upload-form');
    if (uploadForm) {
        uploadForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const authorName = document.getElementById('author-name').value;
            const chapterTitle = document.getElementById('chapter-title').value;
            const fileInput = document.getElementById('file-upload');
            const statusDiv = document.getElementById('upload-status');
            
            if (fileInput.files.length === 0) {
                statusDiv.textContent = 'Please select a file.';
                statusDiv.className = 'upload-status error';
                return;
            }
            
            const file = fileInput.files[0];
            // Note: In a real implementation, this would send to a server
            // For now, we'll just show a success message
            statusDiv.textContent = `Thank you! Your chapter "${chapterTitle}" by ${authorName} has been received. We will review your submission and contact you shortly.`;
            statusDiv.className = 'upload-status success';
            
            // Reset form after 3 seconds
            setTimeout(() => {
                uploadForm.reset();
                statusDiv.textContent = '';
            }, 3000);
        });
    }
});

function showAuthorsContent() {
    document.getElementById('auth-container').style.display = 'none';
    document.getElementById('authors-content').style.display = 'block';
}

function showAuthsContainer() {
    document.getElementById('auth-container').style.display = 'block';
    document.getElementById('authors-content').style.display = 'none';
}
