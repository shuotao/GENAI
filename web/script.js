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
});
