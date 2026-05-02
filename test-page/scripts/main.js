/**
 * Test Page - Main JavaScript
 * Handles all interactive components and features
 */

(function() {
    'use strict';

    // ==========================================================================
    // Feature 4: Theme Toggle (Dark/Light) with System Preference
    // ==========================================================================
    const ThemeManager = {
        STORAGE_KEY: 'testpage-theme',

        init() {
            const savedTheme = localStorage.getItem(this.STORAGE_KEY);
            if (savedTheme) {
                document.documentElement.setAttribute('data-theme', savedTheme);
            } else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
                document.documentElement.setAttribute('data-theme', 'dark');
            }

            const toggleBtn = document.getElementById('themeToggle');
            if (toggleBtn) {
                toggleBtn.addEventListener('click', () => this.toggle());
            }

            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
                if (!localStorage.getItem(this.STORAGE_KEY)) {
                    document.documentElement.setAttribute('data-theme', e.matches ? 'dark' : 'light');
                }
            });
        },

        toggle() {
            const current = document.documentElement.getAttribute('data-theme');
            const next = current === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', next);
            localStorage.setItem(this.STORAGE_KEY, next);
        }
    };

    // ==========================================================================
    // Feature 8: Scroll Progress Indicator
    // ==========================================================================
    const ScrollProgress = {
        element: null,
        ticking: false,

        init() {
            this.element = document.getElementById('scrollProgress');
            if (!this.element) return;

            window.addEventListener('scroll', () => this.update(), { passive: true });
            this.update();
        },

        update() {
            if (!this.ticking) {
                requestAnimationFrame(() => {
                    const scrollTop = window.scrollY;
                    const docHeight = document.documentElement.scrollHeight - window.innerHeight;
                    const progress = docHeight > 0 ? (scrollTop / docHeight) * 100 : 0;

                    this.element.style.width = `${progress}%`;
                    this.element.setAttribute('aria-valuenow', Math.round(progress));
                    this.ticking = false;
                });
                this.ticking = true;
            }
        }
    };

    // ==========================================================================
    // Feature 2: Navigation with Active States
    // ==========================================================================
    const Navigation = {
        nav: null,
        mobileToggle: null,

        init() {
            this.nav = document.getElementById('nav');
            this.mobileToggle = document.getElementById('mobileToggle');
            if (!this.nav) return;

            window.addEventListener('scroll', () => this.onScroll(), { passive: true });
            this.onScroll();

            if (this.mobileToggle) {
                this.mobileToggle.addEventListener('click', () => this.toggleMobileMenu());
            }

            document.querySelectorAll('.nav__link').forEach(link => {
                link.addEventListener('click', () => this.closeMobileMenu());
            });
        },

        onScroll() {
            if (this.nav) {
                this.nav.classList.toggle('scrolled', window.scrollY > 50);
            }
        },

        toggleMobileMenu() {
            const links = this.nav?.querySelector('.nav__links');
            if (links) {
                const isOpen = links.classList.toggle('open');
                this.mobileToggle.setAttribute('aria-expanded', isOpen);
            }
        },

        closeMobileMenu() {
            const links = this.nav?.querySelector('.nav__links');
            if (links) {
                links.classList.remove('open');
                this.mobileToggle?.setAttribute('aria-expanded', 'false');
            }
        }
    };

    // ==========================================================================
    // Feature 3: Feature Grid with Category Filters
    // ==========================================================================
    const FeatureGrid = {
        features: [
            { id: 1, name: 'Animated Gradient', category: 'ui-patterns', icon: 'gradient' },
            { id: 2, name: 'Navigation', category: 'ui-patterns', icon: 'menu' },
            { id: 3, name: 'Feature Grid', category: 'ui-patterns', icon: 'grid' },
            { id: 4, name: 'Theme Toggle', category: 'utilities', icon: 'sun' },
            { id: 5, name: 'Live Clock', category: 'widgets', icon: 'clock' },
            { id: 6, name: 'Accordion FAQ', category: 'ui-patterns', icon: 'chevron' },
            { id: 7, name: 'Copy to Clipboard', category: 'utilities', icon: 'copy' },
            { id: 8, name: 'Scroll Progress', category: 'utilities', icon: 'progress' },
            { id: 9, name: 'Form Components', category: 'ui-patterns', icon: 'form' },
            { id: 10, name: 'Toast Notifications', category: 'utilities', icon: 'bell' },
            { id: 11, name: 'Image Gallery', category: 'widgets', icon: 'image' },
            { id: 12, name: 'Modal Dialog', category: 'ui-patterns', icon: 'dialog' },
            { id: 13, name: 'Tabbed Panels', category: 'ui-patterns', icon: 'tab' },
            { id: 14, name: 'Stats Counter', category: 'widgets', icon: 'chart' }
        ],

        init() {
            const grid = document.querySelector('.features__grid');
            const filterBtns = document.querySelectorAll('.filter-btn');
            if (!grid) return;

            this.render(grid);
            this.bindFilters(filterBtns);
        },

        render(container) {
            container.innerHTML = this.features.map(f => `
                <article class="feature-card" data-category="${f.category}">
                    <div class="feature-card__icon">
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                        </svg>
                    </div>
                    <h3 class="feature-card__title">${f.name}</h3>
                    <p class="feature-card__description">Interactive ${f.name.toLowerCase()} component.</p>
                    <span class="feature-card__badge">${f.category}</span>
                </article>
            `).join('');
        },

        bindFilters(buttons) {
            const grid = document.querySelector('.features__grid');
            buttons.forEach(btn => {
                btn.addEventListener('click', () => {
                    buttons.forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');

                    const filter = btn.dataset.filter;
                    grid.querySelectorAll('.feature-card').forEach(card => {
                        const match = filter === 'all' || card.dataset.category === filter;
                        card.classList.toggle('hidden', !match);
                    });
                });
            });
        }
    };

    // ==========================================================================
    // Feature 5: Live Clock Widget
    // ==========================================================================
    const ClockWidget = {
        interval: null,
        is24h: false,

        init() {
            const container = document.querySelector('.clock-widget');
            if (!container) return;

            const toggle = document.getElementById('clockToggle');
            this.is24h = localStorage.getItem('clock-format') === '24h';
            if (this.is24h) {
                document.body.setAttribute('data-format', '24h');
            }

            if (toggle) {
                toggle.addEventListener('click', () => this.toggleFormat());
            }

            this.update();
            this.interval = setInterval(() => this.update(), 1000);
        },

        update() {
            const timeEl = document.getElementById('clockTime');
            const periodEl = document.getElementById('clockPeriod');
            const dateEl = document.getElementById('clockDate');
            if (!timeEl) return;

            const now = new Date();
            let hours = now.getHours();
            let period = '';

            if (!this.is24h) {
                period = hours >= 12 ? 'PM' : 'AM';
                hours = hours % 12 || 12;
            }

            const minutes = String(now.getMinutes()).padStart(2, '0');
            const seconds = String(now.getSeconds()).padStart(2, '0');

            timeEl.textContent = `${hours}:${minutes}:${seconds}`;
            if (periodEl) periodEl.textContent = period;

            if (dateEl) {
                dateEl.textContent = now.toLocaleDateString('en-US', {
                    weekday: 'long',
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric'
                });
            }
        },

        toggleFormat() {
            this.is24h = !this.is24h;
            localStorage.setItem('clock-format', this.is24h ? '24h' : '12h');
            document.body.setAttribute('data-format', this.is24h ? '24h' : '12h');
            this.update();
        }
    };

    // ==========================================================================
    // Feature 6: Accordion FAQ
    // ==========================================================================
    const Accordion = {
        init() {
            const accordions = document.querySelectorAll('.accordion__item');
            accordions.forEach(item => {
                const trigger = item.querySelector('.accordion__trigger');
                if (trigger) {
                    trigger.addEventListener('click', () => this.toggle(item));
                }
            });
        },

        toggle(item) {
            const isOpen = item.classList.contains('open');
            const trigger = item.querySelector('.accordion__trigger');
            const content = item.querySelector('.accordion__content');

            // Close all others
            document.querySelectorAll('.accordion__item.open').forEach(openItem => {
                if (openItem !== item) {
                    openItem.classList.remove('open');
                    openItem.querySelector('.accordion__trigger')?.setAttribute('aria-expanded', 'false');
                }
            });

            item.classList.toggle('open', !isOpen);
            if (trigger) trigger.setAttribute('aria-expanded', !isOpen);
        }
    };

    // ==========================================================================
    // Feature 7: Copy to Clipboard
    // ==========================================================================
    const CopyToClipboard = {
        init() {
            document.querySelectorAll('.copy-btn').forEach(btn => {
                btn.addEventListener('click', () => this.copy(btn));
            });
        },

        async copy(btn) {
            const text = btn.dataset.copy || btn.closest('[data-copy-text]')?.dataset.copyText || '';
            try {
                await navigator.clipboard.writeText(text);
                this.showState(btn, 'success');
                Toast.show('Copied to clipboard!', 'success');
            } catch {
                this.showState(btn, 'error');
                Toast.show('Failed to copy', 'error');
            }
        },

        showState(btn, state) {
            btn.classList.remove('success', 'error');
            btn.classList.add(state);
            setTimeout(() => btn.classList.remove(state), 2000);
        }
    };

    // ==========================================================================
    // Feature 9: Form Components
    // ==========================================================================
    const FormShowcase = {
        init() {
            const form = document.getElementById('demoForm');
            if (!form) return;

            const textarea = document.getElementById('textareaInput');
            const charCount = document.getElementById('charCount');

            if (textarea && charCount) {
                textarea.addEventListener('input', () => {
                    charCount.textContent = textarea.value.length;
                });
            }

            form.addEventListener('submit', (e) => {
                e.preventDefault();
                Toast.show('Form submitted successfully!', 'success');
            });

            const emailInput = document.getElementById('emailInput');
            const emailError = document.getElementById('emailError');

            if (emailInput && emailError) {
                emailInput.addEventListener('blur', () => {
                    const isValid = emailInput.value.match(/^[^\s@]+@[^\s@]+\.[^\s@]+$/);
                    emailError.textContent = isValid ? '' : 'Please enter a valid email address';
                    emailInput.classList.toggle('form-input--error', !isValid && emailInput.value.length > 0);
                });
            }
        }
    };

    // ==========================================================================
    // Feature 10: Toast Notifications
    // ==========================================================================
    const Toast = {
        container: null,

        init() {
            this.container = document.getElementById('toastContainer');
        },

        show(message, type = 'info', duration = 5000) {
            if (!this.container) return;

            const toast = document.createElement('div');
            toast.className = `toast toast--${type}`;
            toast.innerHTML = `
                <svg class="toast__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    ${this.getIcon(type)}
                </svg>
                <span class="toast__message">${message}</span>
                <button class="toast__close" aria-label="Dismiss">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
            `;

            toast.querySelector('.toast__close').addEventListener('click', () => this.dismiss(toast));
            this.container.appendChild(toast);

            setTimeout(() => this.dismiss(toast), duration);

            toast.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') this.dismiss(toast);
            });
        },

        dismiss(toast) {
            if (!toast.classList.contains('exiting')) {
                toast.classList.add('exiting');
                setTimeout(() => toast.remove(), 200);
            }
        },

        getIcon(type) {
            const icons = {
                success: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline>',
                error: '<circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line>',
                warning: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line>',
                info: '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line>'
            };
            return icons[type] || icons.info;
        }
    };

    // ==========================================================================
    // Feature 11: Lazy-loaded Image Gallery
    // ==========================================================================
    const Gallery = {
        images: [],
        currentIndex: 0,

        init() {
            const gallery = document.getElementById('gallery');
            if (!gallery) return;

            this.images = Array.from({ length: 8 }, (_, i) => ({
                src: `https://picsum.photos/400/400?random=${i + 1}`,
                alt: `Gallery image ${i + 1}`
            }));

            this.render(gallery);
            this.bindLightbox();
        },

        render(container) {
            container.innerHTML = this.images.map((img, i) => `
                <div class="gallery__item" data-index="${i}">
                    <img class="gallery__image" data-src="${img.src}" alt="${img.alt}" loading="lazy">
                </div>
            `).join('');

            // Lazy load with blur-up effect
            const images = container.querySelectorAll('.gallery__image');
            const observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        const img = entry.target;
                        img.src = img.dataset.src;
                        img.onload = () => img.classList.add('loaded');
                        observer.unobserve(img);
                    }
                });
            }, { rootMargin: '100px' });

            images.forEach(img => observer.observe(img));
        },

        bindLightbox() {
            const lightbox = document.getElementById('lightbox');
            if (!lightbox) return;

            document.querySelectorAll('.gallery__item').forEach(item => {
                item.addEventListener('click', () => {
                    this.currentIndex = parseInt(item.dataset.index);
                    this.openLightbox();
                });
            });

            document.getElementById('lightboxClose')?.addEventListener('click', () => this.closeLightbox());
            document.getElementById('lightboxPrev')?.addEventListener('click', () => this.prevImage());
            document.getElementById('lightboxNext')?.addEventListener('click', () => this.nextImage());

            lightbox.addEventListener('click', (e) => {
                if (e.target === lightbox) this.closeLightbox();
            });

            document.addEventListener('keydown', (e) => {
                if (!lightbox.hidden) {
                    if (e.key === 'Escape') this.closeLightbox();
                    if (e.key === 'ArrowLeft') this.prevImage();
                    if (e.key === 'ArrowRight') this.nextImage();
                }
            });
        },

        openLightbox() {
            const lightbox = document.getElementById('lightbox');
            const img = document.getElementById('lightboxImage');
            const counter = document.getElementById('lightboxCounter');
            if (!lightbox || !img) return;

            img.src = this.images[this.currentIndex].src;
            img.alt = this.images[this.currentIndex].alt;
            if (counter) counter.textContent = `${this.currentIndex + 1} / ${this.images.length}`;
            lightbox.hidden = false;
        },

        closeLightbox() {
            const lightbox = document.getElementById('lightbox');
            if (lightbox) lightbox.hidden = true;
        },

        prevImage() {
            this.currentIndex = (this.currentIndex - 1 + this.images.length) % this.images.length;
            this.openLightbox();
        },

        nextImage() {
            this.currentIndex = (this.currentIndex + 1) % this.images.length;
            this.openLightbox();
        }
    };

    // ==========================================================================
    // Feature 12: Keyboard Accessible Modal
    // ==========================================================================
    const Modal = {
        activeTrigger: null,

        init() {
            const modal = document.getElementById('modal');
            if (!modal) return;

            document.getElementById('modalClose')?.addEventListener('click', () => this.close());
            document.getElementById('modalCancel')?.addEventListener('click', () => this.close());
            document.getElementById('modalBackdrop')?.addEventListener('click', () => this.close());

            modal.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') this.close();
                if (e.key === 'Tab') this.trapFocus(e);
            });
        },

        open(trigger) {
            const modal = document.getElementById('modal');
            if (!modal) return;

            this.activeTrigger = trigger;
            modal.hidden = false;
            modal.querySelector('.modal__close')?.focus();
        },

        close() {
            const modal = document.getElementById('modal');
            if (!modal) return;

            modal.hidden = true;
            this.activeTrigger?.focus();
        },

        trapFocus(e) {
            const modal = document.getElementById('modal');
            if (!modal) return;

            const focusable = modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
            const first = focusable[0];
            const last = focusable[focusable.length - 1];

            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        }
    };

    // ==========================================================================
    // Feature 13: Tabbed Content Panels
    // ==========================================================================
    const Tabs = {
        init() {
            const tabs = document.querySelector('.tabs');
            if (!tabs) return;

            tabs.addEventListener('click', (e) => {
                const tab = e.target.closest('.tabs__tab');
                if (tab) this.activate(tab);
            });

            tabs.addEventListener('keydown', (e) => {
                const tabList = tabs.querySelectorAll('.tabs__tab');
                const current = Array.from(tabList).indexOf(document.activeElement);

                if (e.key === 'ArrowRight' && current < tabList.length - 1) {
                    e.preventDefault();
                    tabList[current + 1].focus();
                    this.activate(tabList[current + 1]);
                } else if (e.key === 'ArrowLeft' && current > 0) {
                    e.preventDefault();
                    tabList[current - 1].focus();
                    this.activate(tabList[current - 1]);
                }
            });
        },

        activate(tab) {
            const tabList = document.querySelectorAll('.tabs__tab');
            const panels = document.querySelectorAll('.tabs__panel');

            tabList.forEach(t => {
                const isActive = t === tab;
                t.classList.toggle('active', isActive);
                t.setAttribute('aria-selected', isActive);
            });

            panels.forEach(p => {
                p.classList.toggle('active', p.id === tab.getAttribute('aria-controls'));
                p.hidden = p.id !== tab.getAttribute('aria-controls');
            });
        }
    };

    // ==========================================================================
    // Feature 14: Animated Statistics Counter
    // ==========================================================================
    const StatsCounter = {
        init() {
            const stats = document.querySelectorAll('.stat-card__value');
            if (!stats.length) return;

            const observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        this.animate(entry.target);
                        observer.unobserve(entry.target);
                    }
                });
            }, { threshold: 0.5 });

            stats.forEach(stat => observer.observe(stat));
        },

        animate(element) {
            const target = parseFloat(element.dataset.target);
            const suffix = element.dataset.suffix || '';
            const prefix = element.dataset.prefix || '';
            const duration = 2000;
            const start = performance.now();
            const isDecimal = target % 1 !== 0;

            const tick = (now) => {
                const elapsed = now - start;
                const progress = Math.min(elapsed / duration, 1);
                const eased = 1 - Math.pow(1 - progress, 3);
                const current = target * eased;

                element.textContent = `${prefix}${isDecimal ? current.toFixed(1) : Math.round(current)}${suffix}`;

                if (progress < 1) {
                    requestAnimationFrame(tick);
                }
            };

            requestAnimationFrame(tick);
        }
    };

    // ==========================================================================
    // Initialize All Features
    // ==========================================================================
    document.addEventListener('DOMContentLoaded', () => {
        ThemeManager.init();
        ScrollProgress.init();
        Navigation.init();
        FeatureGrid.init();
        ClockWidget.init();
        Accordion.init();
        CopyToClipboard.init();
        FormShowcase.init();
        Toast.init();
        Gallery.init();
        Modal.init();
        Tabs.init();
        StatsCounter.init();
    });

})();
