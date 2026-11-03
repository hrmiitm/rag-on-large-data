    /// Experiment adapter: validated query injection into RAM only. Never persists.
    pub fn inject_query(&self, text: &str, vector: Vec<f32>) -> Result<(), String> {
        vector_norm(&vector, self.profile.dimensions)?;
        self.queries.lock().map_err(|_| "Query cache poisoned")?.insert(text.trim().to_string(), vector);
        Ok(())
    }
    pub fn has_query(&self, text: &str) -> bool {
        self.queries.lock().map(|q|q.contains_key(text.trim())).unwrap_or(false)
    }
    pub fn candidate_vector(&self, index: usize) -> Option<&[f32]> {
        self.documents.get(index).map(|v|v.values.as_slice())
    }

