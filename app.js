const sections = [...document.querySelectorAll(".section[id]")];
const links = [...document.querySelectorAll(".site-nav nav a[href^='#']")];

const observer = new IntersectionObserver((entries) => {
  const visible = entries
    .filter((entry) => entry.isIntersecting)
    .sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0];
  if (!visible) return;
  links.forEach((link) => {
    link.classList.toggle("active", link.getAttribute("href") === `#${visible.target.id}`);
  });
}, { threshold: [0.45, 0.65] });

sections.forEach((section) => observer.observe(section));
