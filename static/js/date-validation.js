/**
 * Validação de datas - Garante que a data final nunca seja menor que a data inicial
 * Validação ocorre apenas no momento do envio do formulário
 */
document.addEventListener('DOMContentLoaded', function() {
    // Função para validar formulários com pares de datas
    function setupFormValidation() {
        // Encontrar todos os formulários que contêm campos de data
        const forms = document.querySelectorAll('form');
        
        forms.forEach(form => {
            // Verificar se o formulário tem campos de data inicial e final
            const startDateInput = form.querySelector('#start_date, #date');
            const endDateInput = form.querySelector('#end_date, #recurring_end_date');
            
            if (startDateInput && endDateInput) {
                // Adicionar validação no envio do formulário
                form.addEventListener('submit', function(event) {
                    if (startDateInput.value && endDateInput.value) {
                        const startDate = new Date(startDateInput.value);
                        const endDate = new Date(endDateInput.value);
                        
                        if (endDate < startDate) {
                            event.preventDefault();
                            alert('A data final não pode ser menor que a data inicial.');
                        }
                    }
                });
            }
        });
    }
    
    // Configurar validação para todos os formulários com datas
    setupFormValidation();
    
    // Validação específica para formulários de orçamento
    const budgetForms = document.querySelectorAll('.budget-form');
    budgetForms.forEach(form => {
        // A validação já está configurada pelo setupFormValidation
        // Esta é apenas uma configuração adicional específica se necessário
    });
});
