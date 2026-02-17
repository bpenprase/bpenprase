// Chapter data
const chapters = [
    {
        number: 1,
        title: "The Need for Innovation in US Higher Education",
        abstract: "This chapter examines the mounting challenges facing US higher education while introducing a framework for institutional renewal. Despite predictions of imminent collapse, the sector has proven resilient yet faces serious structural problems: a broken business model marked by skyrocketing tuition, declining public support, a 'demographic cliff' threatening future enrollment, and administrative cost pressures. The chapter documents the paradox of enduring value—bachelor's degrees still yield significant lifetime earnings premiums—alongside growing inequities that concentrate benefits at elite institutions while hundreds of smaller colleges face closure or merger. The analysis identifies key dysfunctions including prestige-driven governance paradigms, misalignment between educational offerings and student needs, and declining completion rates. However, the chapter argues these challenges create opportunities for innovation. It proposes solutions explored throughout the book: entrepreneurial approaches to university management, new start-up institutions serving underrepresented populations globally, teaching innovations at research universities, the rise of mega-universities delivering value at scale, artificial intelligence integration, and reimagined residential learning transformative elements of traditional liberal arts education with technological efficiency, accessibility, and adaptability to an AI-permeated world."
    },
    {
        number: 2,
        title: "Adapting to the Financial Realities of Higher Education: Balancing Tradition and Change",
        abstract: "This chapter examines the financial realities facing American higher education, exploring why college costs have risen faster than any sector of the economy. Through case studies of Yale University and liberal colleges, the chapter reveals how labor-intensive educational institutions resist the efficiency gains typical of other industries. Through case studies of Yale University and liberal colleges, the chapter reveals how labor-intensive educational institutions resist the efficiency gains typical of other industries. The analysis demonstrates how labor-intensive educational institutions resist the efficiency gains typical of other industries, exploring that while elite institutions hold billion in endowments, smaller colleges face closure or merger. The chapter reveals that educational endowments endowments provide minimal operating support. Various revenue diversification strategies are examined, including international student recruitment, external partnerships, intellectual property licensing. The analysis addresses critical questions about the sustainability of traditional higher education missions, including departmental organization, and residual learning models. While acknowledging the urgent need for business model reform, the chapter argues that purely cost-focused approaches risk sacrificing the intangible benefits—transformative encounters, mentorship, and intellectual community—that make higher education valuable to society."
    },
    {
        number: 3,
        title: "Entrepreneurial Cultures and Lessons for Higher Education",
        abstract: "Universities face unprecedented existential threats from demographic decline and unsustainable cost structures. Yet institutions resist to change. This chapter explores the paradox of higher education: institutions that simultaneously preserve historical knowledge while building futures, constrained countries and traditions and what Christensen and March termed 'organized anarchy.' Drawing on institutional management frameworks including Porter's Five Forces and Christensen's disruption theory, the chapter analyzes competitive pressures reshaping academia—from mega-universities directly addressing alternative credentials threatening traditional degree pathways. Arizona State University under Michael Crow emerges as a transformative example, demonstrating that universities can fundamentally reinvent themselves through bold leadership, interdisciplinary innovation, and 'Blue Ocean' strategies. The chapter synthesizes organizational culture theories from Schein, Creative and others to propose pathways toward learning organizations capable of adaptive change. Through case studies of Mills College, Hampshire College, and Sweet Briar College—institutions that navigated near-closure through strategic reinvention—the chapter identifies essential elements for institutional survival: cultural entrepreneurship, community mobilization, and fundamental reconsideration of institutional purpose. The analysis concludes that higher education's future depends on developing entrepreneurial cultures that balance tradition with transformation."
    },
    {
        number: 4,
        title: "The Emergence of New Universities in the 21st Century",
        abstract: "This chapter examines the global emergence of new universities in the 21st century, arguing that startup institutions are essential for pioneering innovations in curriculum, pedagogy, and institutional vision that legacy universities struggle to achieve. While the United States faces a stagnant higher education ecosystem—with more campuses closing than opening and accreditation barriers limiting new frameworks—the chapter demonstrates transformative possibilities across the Global South, which represents over 85 percent of the world's population and where institutions like Open Leadership University, Ashesi University, African Leadership University, and the Asian University for Women are addressing unmet needs for quality affordable education, women's empowerment, and critical leadership. These institutions collectively offer a blueprint for the 'future-proof' university. The chapter highlights how new liberal arts universities in Pakistan, India, Vietnam, and Bangladesh are grounding curricula in local cultural traditions while preparing graduates for global engagement. These innovative models create far more robust foundations for institutional renewal than elite universities' incremental adjustments. The chapter concludes by noting the challenge of scaling these innovations beyond individual centers to systematically transform institutions and ensure these advances benefit all of higher education."
    },
    {
        number: 5,
        title: "Teaching Innovation at the Top R1 Universities",
        abstract: "America's top research universities—including MIT, Harvard, Princeton, Stanford, Caltech, UC Berkeley, Yale, and Georgetown—are increasingly directing their world-class talent toward transforming undergraduate education through innovation. The chapter explores how computational theory from Christensen, Garvin, and Senge, these 'protected innovation spaces' operate outside traditional administrative collaboration between disciplinary faculty scientists, computer scientists, and educational researchers. Notable examples include MIT's Media Lab and Open Learning Initiative (creators of SCRATCH and OpenCourseWare), Harvard's Bak Center and Initiative for Learning and Teaching, Stanford's d.school and Digital Education programs, Caltech's CTLO and SURF undergraduate research programs, UC Berkeley's Discovery Initiative, Yale's Poorva Center, and Georgetown's Hci House. These centers have achieved remarkable national and global impact: MIT's OpenCourseWare has reached 100 million users across 70 languages, and SCRATCH has reached 103 million users worldwide. As training grounds for doctoral students who will become tomorrow's professors, these centers shape not just individual pedagogical practice but also the future of higher education. The chapter concludes by noting the challenge of scaling these innovations beyond individual centers to systematically transform institutions and ensure these advances benefit all of higher education."
    },
    {
        number: 6,
        title: "Rapidly Growing Universities",
        abstract: "This chapter examines four rapidly growing American universities—Arizona State University, Southern New Hampshire University, Western Governors University, and Northeastern University—that have collectively transformed higher education by serving over 700,000 students through innovative models developed within the past thirty years. These institutions have challenged fundamental assumptions that quality requires exclusivity and that learning must be tied to geographic location through online learning, ASU pioneered scalable online education through ASU Online, reaching over 170,000 students while maintaining R1 research status and developing transformative corporate partnerships with companies like Starbucks and Uber. SNHU revolutionized accessible online education while becoming the world's largest producer of teachers and nurses. Northeastern University developed a global network of 13 campuses emphasizing experiential learning through cooperative education programs spanning 158 countries. All four institutions share common strategies embracing technology as an enabler, forming employer partnerships to ensure workforce alignment, maintaining robust student support systems, and demonstrating that scale and quality innovation can coexist. Their success offers valuable lessons for institutions navigating higher education's uncertain future, proving that dramatic innovation is possible through visionary leadership that aligns institutional values with educational models and organizational structures."
    },
    {
        number: 7,
        title: "AI Goes to College: Higher Education in the Age of AI",
        abstract: "This chapter examines the transformative impact of artificial intelligence on higher education, tracing AI development from its origins in the 1950s through the latest large language models. The chapter explores how modern AI systems work, including neural networks, transformers, and attention mechanisms that enable sophisticated language processing. It surveys the emerging field of Artificial Intelligence in Education (AIED), highlighting intelligent tutoring systems like ALEKS that personalize learning through cognitive modeling, as well as AI tools designed to enhance human collaboration and creativity rather than simply provide answers. The chapter presents theoretical frameworks for leading scholars including Ethan Mallick, Jose Antonio Bowen, Joseph Aoun, and Bryan Alexander, who advocate for 'co-intelligence' approaches where AI augments rather than replaces human thinking. It profiles pioneering AI-focused institutions including the Roux Institute, Middleware Lab at Sacred University of AI, and the Insitutions where AI augments decision-making. A major research universities. Throughout, the chapter emphasizes the critical importance of maintaining human-centered approaches, developing AI literacy and ethical frameworks, and preserving meaningful human interactions as AI becomes increasingly integrated into educational practice."
    },
    {
        number: 8,
        title: "Reimagining the Residential University",
        abstract: "This chapter argues that residential living-learning communities represent one of higher education's most powerful yet underutilized tools for transformative learning. Drawing on decades of research from Blimling and Astin, and research conducted at Austin, Pascarella and Terenzini, Kuh, and Chambliss and Takacs, the chapter demonstrates that where students live profoundly shapes what they learn—with residence halls functioning as critical educational settings rather than just participatory amenities. The chapter examines how high-impact practices identified by AAC&U, including first-year seminars, undergraduate research, service learning, and capstone projects, can be intentionally woven into residential environments. After reviewing best practices from elite institutions such as Yale, Princeton, and selective universities, innovative models that deliver exceptional residential education at reduced cost: Honors Colleges providing intimate learning within large research universities, work colleges eliminating tuition through student labor, and the Greenway Institute's 2+2 model combining intensive on-campus learning with paid professional experience. The chapter concludes that synthesizing these innovations—integrating academic and student affairs, leveraging student labor, and reimagining the traditional four-year residential model—can make transformative residential education accessible to far more students."
    },
    {
        number: 9,
        title: "Making the Future-Proof University",
        abstract: "Higher education faces existential challenges: a broken financial model, mounting student debt, demographic enrollment cliff, and fears of institutional disruption. This chapter argues that universities must transform from 'organized anarchy' into entrepreneurial learning organizations to survive. Drawing lessons from diverse institutional models—Arizona State's 'Fifth Wave' innovation, startup universities like Olin College and Miners, new universities including Western Governors and Southern New Hampshire, and innovative global institutions from Africa to Asia—the chapter identifies key strategies for building future-proof universities. These include creative revenue diversification, disaggregated faculty roles, competency-based education, integrated student services, and AI emerged as 'co-intelligence' that should either replace human thinking, guided by philosophical frameworks, intentionality, and focus on experiential learning. Penprase presents a model for the New Liberal Arts College synthesizing bold innovations, MIT's Educational Institution with its teaching-focused faculty model, a modular university system enabling flexible specialization, and AI-enabled learning platforms like Master and Spark. The future proof university will combine technological efficiency with human-centered values, delivering accessible, affordable, transformative education while preserving the essential 'minds rubbing against minds' that residential communities provide. The longer-term future of education in the age of AI is considered by considering the potential of a renaissance of learning powered by ethical and thoughtful uses of education."
    }
];

// Get excerpt of abstract (first 200 characters)
function getExcerpt(text, length = 200) {
    if (text.length <= length) return text;
    return text.substring(0, length) + '...';
}

// Populate chapters on page load
document.addEventListener('DOMContentLoaded', function() {
    const chaptersContainer = document.querySelector('.chapters-grid');
    
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
                    <span class="abstract-excerpt">${excerpt}</span>
                    <span class="abstract-full" style="display:none;">${chapter.abstract}</span>
                    <a href="#" class="read-more-link"> Read More</a>
                </p>
            </div>
        `;
        
        // Handle chapter card expand/collapse
        chapterCard.addEventListener('click', function(e) {
            // Don't toggle if clicking the read more link
            if (e.target.classList.contains('read-more-link')) {
                return;
            }
            this.classList.toggle('active');
        });
        
        // Handle read more link
        const readMoreLink = chapterCard.querySelector('.read-more-link');
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
