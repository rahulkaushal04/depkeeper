/* ============================================================
 * Extra JavaScript for depkeeper Documentation
 * ============================================================
 * Enhancements for Material for MkDocs theme
 * Version: 1.0.0
 * ============================================================ */

(function() {
    'use strict';

    /* ============================================================
     * Utility Functions
     * ============================================================ */

    /**
     * Safely query selector with error handling
     */
    function safeQuerySelector(selector, context = document) {
        try {
            return context.querySelector(selector);
        } catch (e) {
            console.warn(`Invalid selector: ${selector}`, e);
            return null;
        }
    }

    /**
     * Safely query all selectors with error handling
     */
    function safeQuerySelectorAll(selector, context = document) {
        try {
            return context.querySelectorAll(selector);
        } catch (e) {
            console.warn(`Invalid selector: ${selector}`, e);
            return [];
        }
    }

    /**
     * Debounce function to limit event firing
     */
    function debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    /* ============================================================
     * Copy Button Enhancements
     * ============================================================ */

    function enhanceCopyButtons() {
        const copyButtons = safeQuerySelectorAll('.md-clipboard');

        copyButtons.forEach(button => {
            button.addEventListener('click', function() {
                // Create and show success message
                const originalTitle = button.title;
                button.title = 'Copied!';

                // Add visual feedback
                button.classList.add('md-clipboard--copied');

                // Reset after 2 seconds
                setTimeout(() => {
                    button.title = originalTitle;
                    button.classList.remove('md-clipboard--copied');
                }, 2000);
            });
        });
    }

    /* ============================================================
     * External Links Handler
     * ============================================================ */

    function handleExternalLinks() {
        const currentDomain = window.location.hostname;
        const links = safeQuerySelectorAll('a[href^="http"]');

        links.forEach(link => {
            try {
                const linkUrl = new URL(link.href);
                const isExternal = linkUrl.hostname !== currentDomain &&
                                 !linkUrl.hostname.endsWith('depkeeper.dev');

                if (isExternal) {
                    // Add external link attributes
                    link.setAttribute('target', '_blank');
                    link.setAttribute('rel', 'noopener noreferrer');

                    // Add visual indicator (if not already present)
                    if (!link.querySelector('.external-link-icon')) {
                        const icon = document.createElement('span');
                        icon.className = 'external-link-icon';
                        icon.innerHTML = ' ↗';
                        icon.style.fontSize = '0.8em';
                        icon.style.marginLeft = '0.2em';
                        link.appendChild(icon);
                    }
                }
            } catch (e) {
                // Skip invalid URLs
                console.debug('Invalid URL:', link.href);
            }
        });
    }

    /* ============================================================
     * Table of Contents Enhancements
     * ============================================================ */

    function enhanceTableOfContents() {
        const tocLinks = safeQuerySelectorAll('.md-nav--secondary a[href^="#"]');
        const sections = [];

        // Build sections array
        tocLinks.forEach(link => {
            const targetId = link.getAttribute('href').slice(1);
            const target = document.getElementById(targetId);
            if (target) {
                sections.push({
                    link: link,
                    target: target,
                    id: targetId
                });
            }
        });

        if (sections.length === 0) return;

        // Highlight active section on scroll
        const highlightActiveSection = debounce(() => {
            const scrollPosition = window.scrollY + 100;

            let activeSection = null;
            for (let i = sections.length - 1; i >= 0; i--) {
                const section = sections[i];
                if (section.target.offsetTop <= scrollPosition) {
                    activeSection = section;
                    break;
                }
            }

            if (activeSection) {
                sections.forEach(s => {
                    s.link.classList.remove('active-toc-link');
                });
                activeSection.link.classList.add('active-toc-link');
            }
        }, 50);

        window.addEventListener('scroll', highlightActiveSection);
        highlightActiveSection(); // Initial highlight
    }

    /* ============================================================
     * Code Block Enhancements
     * ============================================================ */

    function enhanceCodeBlocks() {
        const codeBlocks = safeQuerySelectorAll('.highlight');

        codeBlocks.forEach((block, index) => {
            // Add line numbers toggle (if not already present)
            const pre = block.querySelector('pre');
            if (pre && !block.querySelector('.code-block-header')) {
                const header = document.createElement('div');
                header.className = 'code-block-header';

                // Detect language
                const languageClass = Array.from(block.classList)
                    .find(cls => cls.startsWith('language-'));
                const language = languageClass ?
                    languageClass.replace('language-', '').toUpperCase() :
                    'CODE';

                const languageLabel = document.createElement('span');
                languageLabel.className = 'code-language-label';
                languageLabel.textContent = language;
                languageLabel.style.fontSize = '0.75em';
                languageLabel.style.opacity = '0.7';
                languageLabel.style.padding = '0.25rem 0.5rem';

                header.appendChild(languageLabel);
                block.insertBefore(header, block.firstChild);
            }
        });
    }

    /* ============================================================
     * Keyboard Shortcuts
     * ============================================================ */

    function setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Don't trigger if user is typing in an input
            if (e.target.tagName === 'INPUT' ||
                e.target.tagName === 'TEXTAREA' ||
                e.target.isContentEditable) {
                return;
            }

            // "/" or "s" to focus search
            if (e.key === '/' || (e.key === 's' && !e.ctrlKey && !e.metaKey)) {
                e.preventDefault();
                const searchInput = safeQuerySelector('.md-search__input');
                if (searchInput) {
                    searchInput.focus();
                }
            }

            // "Escape" to close search
            if (e.key === 'Escape') {
                const searchInput = safeQuerySelector('.md-search__input');
                if (searchInput && document.activeElement === searchInput) {
                    searchInput.blur();
                }
            }

            // "t" to scroll to top
            if (e.key === 't' && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                window.scrollTo({
                    top: 0,
                    behavior: 'smooth'
                });
            }
        });
    }

    /* ============================================================
     * Table Enhancements
     * ============================================================ */

    function enhanceTables() {
        const tables = safeQuerySelectorAll('.md-typeset table:not([class])');

        tables.forEach(table => {
            // Make tables responsive by wrapping in a container
            if (!table.parentElement.classList.contains('table-wrapper')) {
                const wrapper = document.createElement('div');
                wrapper.className = 'table-wrapper';
                wrapper.style.overflowX = 'auto';
                wrapper.style.marginBottom = '1rem';

                table.parentNode.insertBefore(wrapper, table);
                wrapper.appendChild(table);
            }

            // Add sortable class indicator
            const headers = table.querySelectorAll('th');
            headers.forEach(header => {
                if (!header.querySelector('.sortable-icon')) {
                    header.style.cursor = 'pointer';
                    header.title = 'Click to sort';
                }
            });
        });
    }

    /* ============================================================
     * Progress Indicator
     * ============================================================ */

    function addReadingProgressBar() {
        // Create progress bar
        const progressBar = document.createElement('div');
        progressBar.id = 'reading-progress';
        progressBar.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 0%;
            height: 3px;
            background: var(--md-primary-fg-color);
            z-index: 1000;
            transition: width 0.1s ease;
        `;
        document.body.appendChild(progressBar);

        // Update on scroll
        const updateProgress = debounce(() => {
            const windowHeight = window.innerHeight;
            const documentHeight = document.documentElement.scrollHeight;
            const scrollTop = window.scrollY;
            const maxScroll = documentHeight - windowHeight;

            if (maxScroll > 0) {
                const progress = (scrollTop / maxScroll) * 100;
                progressBar.style.width = Math.min(progress, 100) + '%';
            }
        }, 10);

        window.addEventListener('scroll', updateProgress);
        updateProgress(); // Initial update
    }

    /* ============================================================
     * Back to Top Button Enhancement
     * ============================================================ */

    function enhanceBackToTop() {
        const backToTopButton = safeQuerySelector('.md-top');

        if (backToTopButton) {
            backToTopButton.addEventListener('click', (e) => {
                e.preventDefault();
                window.scrollTo({
                    top: 0,
                    behavior: 'smooth'
                });
            });
        }
    }

    /* ============================================================
     * Search Enhancements
     * ============================================================ */

    function enhanceSearch() {
        const searchInput = safeQuerySelector('.md-search__input');

        if (searchInput) {
            // Add placeholder text
            if (!searchInput.placeholder) {
                searchInput.placeholder = 'Search documentation... (Press / or s)';
            }

            // Show search shortcut hint
            searchInput.addEventListener('focus', () => {
                searchInput.setAttribute('data-focused', 'true');
            });

            searchInput.addEventListener('blur', () => {
                searchInput.removeAttribute('data-focused');
            });
        }
    }

    /* ============================================================
     * Copy Code Blocks with Language Info
     * ============================================================ */

    function enhanceCodeCopy() {
        // Add custom CSS for copied state
        const style = document.createElement('style');
        style.textContent = `
            .md-clipboard--copied {
                opacity: 0.7;
            }
            .active-toc-link {
                font-weight: 600;
                color: var(--md-primary-fg-color) !important;
            }
        `;
        document.head.appendChild(style);
    }

    /* ============================================================
     * Anchor Link Hash Handling
     * ============================================================ */

    function handleAnchorLinks() {
        // Smooth scroll to hash on page load
        if (window.location.hash) {
            setTimeout(() => {
                const target = document.getElementById(window.location.hash.slice(1));
                if (target) {
                    target.scrollIntoView({
                        behavior: 'smooth',
                        block: 'start'
                    });
                }
            }, 100);
        }

        // Handle hash changes
        window.addEventListener('hashchange', () => {
            const target = document.getElementById(window.location.hash.slice(1));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    }

    /* ============================================================
     * Initialize All Features
     * ============================================================ */

    function init() {
        // Wait for DOM to be ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', init);
            return;
        }

        // Wait for Material theme to be ready
        if (typeof app === 'undefined') {
            setTimeout(init, 100);
            return;
        }

        try {
            console.log('Initializing depkeeper documentation enhancements...');

            enhanceCopyButtons();
            handleExternalLinks();
            enhanceTableOfContents();
            enhanceCodeBlocks();
            setupKeyboardShortcuts();
            enhanceTables();
            addReadingProgressBar();
            enhanceBackToTop();
            enhanceSearch();
            enhanceCodeCopy();
            handleAnchorLinks();

            console.log('Documentation enhancements loaded successfully');

            // Re-run enhancements when navigating (for instant loading)
            if (app && app.document$) {
                app.document$.subscribe(() => {
                    setTimeout(() => {
                        handleExternalLinks();
                        enhanceCodeBlocks();
                        enhanceTables();
                        enhanceTableOfContents();
                    }, 100);
                });
            }
        } catch (error) {
            console.error('Error initializing documentation enhancements:', error);
        }
    }

    // Start initialization
    init();

    /* ============================================================
     * Export to window for debugging (optional)
     * ============================================================ */

    window.depkeeperDocs = {
        version: '1.0.0',
        init: init
    };

})();
