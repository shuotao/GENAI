document.addEventListener('DOMContentLoaded', () => {
    const sections = document.querySelectorAll('.section');
    const navItems = document.querySelectorAll('.nav-item');
    const container = document.querySelector('.container');

    // 1. Intersection Observer for Scrolling Detection
    const observerOptions = {
        root: container, // Use the scrollable container as the root
        threshold: 0.5 // Trigger when 50% of the section is visible
    };

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                // Remove active class from all items
                navItems.forEach(item => item.classList.remove('active'));

                // Add active class to the matching nav item
                const id = entry.target.getAttribute('id');
                const activeNavItem = document.querySelector(`.nav-item[data-target="${id}"]`);
                if (activeNavItem) {
                    activeNavItem.classList.add('active');
                }
            }
        });
    }, observerOptions);

    sections.forEach(section => {
        observer.observe(section);
    });

    // 2. Click to Scroll
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const targetId = item.getAttribute('data-target');
            const targetSection = document.getElementById(targetId);
            if (targetSection) {
                // Determine the scroll position relative to the container
                // Since container is relative, offsetTop gives the correct position
                container.scrollTo({
                    top: targetSection.offsetTop,
                    behavior: 'smooth'
                });
            }
        });
    });
    // 3. Tech Drawer Logic (Iframe Version for Local Files)
    const drawerOverlay = document.getElementById('tech-drawer-overlay');
    const techDrawer = document.getElementById('tech-drawer');
    const closeDrawerBtn = document.getElementById('close-drawer');
    const techIframe = document.getElementById('tech-iframe');
    const techLinks = document.querySelectorAll('.tech-link-btn');

    function openDrawer(url) {
        if (!techDrawer || !drawerOverlay || !techIframe) return;
        techIframe.src = url;
        techDrawer.classList.add('open');
        drawerOverlay.classList.add('open');
        document.body.style.overflow = 'hidden';
    }

    function closeDrawer() {
        if (!techDrawer || !drawerOverlay || !techIframe) return;
        techDrawer.classList.remove('open');
        drawerOverlay.classList.remove('open');
        document.body.style.overflow = '';
        techIframe.src = 'about:blank'; // Clear content
    }

    techLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const url = link.getAttribute('href');
            openDrawer(url);
        });
    });

    if (closeDrawerBtn) closeDrawerBtn.addEventListener('click', closeDrawer);
    if (drawerOverlay) drawerOverlay.addEventListener('click', closeDrawer);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && techDrawer.classList.contains('open')) closeDrawer();
    });
});
