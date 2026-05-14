(function() {
    // Immediate execution to prevent flash of wrong theme
    function getSavedTheme() {
        return localStorage.getItem('global-theme') || 'light';
    }
    
    document.documentElement.setAttribute('data-theme', getSavedTheme());
    
    // Bind toggle buttons when DOM is loaded
    document.addEventListener('DOMContentLoaded', function() {
        const toggleButtons = document.querySelectorAll('.global-theme-toggle');
        
        function updateButtonText(btn) {
            const currentTheme = document.documentElement.getAttribute('data-theme');
            if (btn.tagName === 'BUTTON') {
                btn.innerHTML = currentTheme === 'dark' ? '<i class="fas fa-sun"></i> 浅色' : '<i class="fas fa-moon"></i> 深色';
            }
        }
        
        function toggleTheme() {
            let currentTheme = document.documentElement.getAttribute('data-theme');
            let newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            
            document.documentElement.setAttribute('data-theme', newTheme);
            localStorage.setItem('global-theme', newTheme);
            
            toggleButtons.forEach(updateButtonText);
        }
        
        toggleButtons.forEach(btn => {
            btn.addEventListener('click', toggleTheme);
            updateButtonText(btn); // Set initial state
        });
    });
})();
